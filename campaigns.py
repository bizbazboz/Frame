"""Project-scoped campaign management with ordered image selections."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import abort, flash, g, redirect, render_template, request, url_for


def register_campaigns(app, db, Group, Version, Campaign, Image, Destination, Account, Platform):
    def scoped_campaign(id):
        return Campaign.query.join(Group).filter(Campaign.id == id, Group.project_id == g.project.id).first_or_404()

    @app.get('/campaigns')
    def campaigns():
        query = Campaign.query.join(Group).filter(Group.project_id == g.project.id)
        search = request.args.get('q', '').strip()
        if search:
            query = query.filter(Campaign.name.icontains(search, autoescape=True))
        destinations = db.session.query(Destination.campaign_id).join(Account)
        filtering = False
        for key, column in [('account', Destination.account_id), ('platform', Account.platform_id)]:
            value = request.args.get(key, '')
            if value:
                try:
                    number = int(value)
                except ValueError:
                    abort(400, 'Invalid account or platform.')
                destinations = destinations.filter(column == number)
                filtering = True
        status = request.args.get('status', '')
        if status not in ('', 'planned', 'published', 'unassigned'):
            abort(400)
        if status == 'unassigned':
            query = query.filter(~Campaign.destinations.any())
        elif status:
            destinations = destinations.filter(Destination.status == status)
            filtering = True
        for key in ('start', 'end'):
            if request.args.get(key):
                try:
                    date = datetime.strptime(request.args[key], '%Y-%m-%d')
                    destinations = destinations.filter(Destination.published_at >= date) if key == 'start' else destinations.filter(Destination.published_at < date + timedelta(days=1))
                except (ValueError, OverflowError):
                    abort(400, 'Invalid date.')
                filtering = True
        if filtering:
            query = query.filter(Campaign.id.in_(destinations))
        pagination = query.order_by(Campaign.id.desc()).paginate(per_page=30, max_per_page=30, error_out=False)
        def page_url(page):
            values = request.args.to_dict()
            values['page'] = page
            return url_for('campaigns', **values)
        return render_template('campaigns.html', items=pagination.items, pagination=pagination, page_url=page_url,
                               accounts=Account.query.order_by(Account.display_name).all(), platforms=Platform.query.order_by(Platform.name).all())

    @app.route('/campaigns/new', methods=['GET', 'POST'])
    @app.route('/campaign/<int:group_id>/new', methods=['GET', 'POST'])
    @app.route('/campaign/edit/<int:campaign_id>', methods=['GET', 'POST'])
    def campaign(group_id=None, campaign_id=None):
        item = scoped_campaign(campaign_id) if campaign_id else None
        photo = item.group if item else Group.query.filter_by(id=group_id, project_id=g.project.id).first_or_404() if group_id else None
        if not item and photo and photo.state == 'never_post':
            abort(403, 'Move this group to Pool or Staging before creating a campaign.')
        current = item.versions if item else ([photo.versions[-1]] if photo and photo.versions else [])
        existing_ids = {version.id for version in current} if item else set()
        if request.method == 'POST':
            values = request.form.getlist('version_ids') if 'version_ids' in request.form else request.form.getlist('version_id')
            try:
                ids = [int(value) for value in values]
                account_ids = {int(value) for value in request.form.getlist('accounts')}
            except ValueError:
                abort(400, 'Invalid selection.')
            name = request.form.get('name', '').strip()
            if not name or len(name) > 200 or not ids or len(ids) != len(set(ids)):
                abort(400, 'Choose a name and at least one image, without duplicates.')
            available = Version.query.join(Group).filter(Version.id.in_(ids), Group.project_id == g.project.id).all()
            if len(available) != len(ids):
                abort(400, 'All images must belong to this project.')
            by_id = {version.id: version for version in available}
            versions = [by_id[id] for id in ids]
            if any(version.group.state == 'never_post' and version.id not in existing_ids for version in versions):
                abort(403, 'Move Never Post photos back to Pool or Staging before adding them.')
            if not item:
                item = Campaign(name=name, group=versions[0].group, version=versions[0])
                db.session.add(item)
            item.name, item.group, item.version = name, versions[0].group, versions[0]
            old_images = {image.version_id: image for image in item.images}
            for image in list(item.images):
                if image.version_id not in ids:
                    item.images.remove(image)
            for position, version in enumerate(versions):
                image = old_images.get(version.id)
                if image is None:
                    image = Image(version=version, campaign=item)
                    db.session.add(image)
                image.position = position
            accounts = Account.query.filter(Account.id.in_(account_ids)).all()
            if len(accounts) != len(account_ids):
                abort(400, 'An account no longer exists.')
            existing = {destination.account_id: destination for destination in item.destinations}
            for destination in list(item.destinations):
                if destination.account_id not in account_ids:
                    item.destinations.remove(destination)
            for account in accounts:
                destination = existing.get(account.id)
                if not destination:
                    destination = Destination(account=account, campaign=item)
                    db.session.add(destination)
                status = request.form.get(f'status_{account.id}', 'planned')
                if status not in ('planned', 'published'):
                    abort(400, 'Invalid publication status.')
                date = request.form.get(f'date_{account.id}', '').strip()
                try:
                    published = datetime.fromisoformat(date) if date else (destination.published_at or datetime.now(timezone.utc).replace(tzinfo=None))
                    if published.tzinfo:
                        published = published.astimezone(timezone.utc).replace(tzinfo=None)
                except ValueError:
                    abort(400, 'Invalid publication date.')
                destination.status = status
                destination.published_at = published if status == 'published' else None
                destination.post_url = request.form.get(f'url_{account.id}', '').strip()
                if destination.post_url and urlsplit(destination.post_url).scheme not in ('https', 'http'):
                    abort(400, 'Post URLs must use HTTP or HTTPS.')
            if any(destination.status == 'published' for destination in item.destinations):
                for version in versions:
                    version.group.state = 'final'
            db.session.commit()
            flash('Campaign saved.')
            return redirect(url_for('campaigns'))
        available = Version.query.join(Group).filter(Group.project_id == g.project.id).order_by(Group.id.desc(), Version.created_at.desc()).all()
        available = [version for version in available if version.group.state != 'never_post' or version.id in existing_ids]
        return render_template('campaign.html', photo=photo, item=item, selected_versions=current, available_versions=available,
                               accounts=Account.query.order_by(Account.display_name).all())

    @app.route('/campaign/<int:campaign_id>/delete', methods=['GET', 'POST'])
    def delete_campaign(campaign_id):
        item = scoped_campaign(campaign_id)
        if request.method == 'POST':
            if request.form.get('confirm') != 'delete':
                abort(400, 'Deletion confirmation required.')
            db.session.delete(item)
            db.session.commit()
            flash('Campaign deleted.')
            return redirect(url_for('campaigns'))
        return render_template('delete_campaign.html', item=item)
