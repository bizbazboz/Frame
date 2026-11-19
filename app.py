import os
import hashlib
import hmac
from urllib.parse import urlencode
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, g, abort, flash, redirect, render_template, request, send_from_directory, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import exists
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from filelock import FileLock
from image_analysis import inspect_image
from media_deletion import delete_with_media, MediaDeletionError
from database_setup import register_database_commands

load_dotenv()
db = SQLAlchemy()
group_tags = db.Table('group_tags', db.Column('group_id', db.ForeignKey('photo_group.id'), primary_key=True), db.Column('tag_id', db.ForeignKey('tag.id'), primary_key=True))

class PhotoGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(20), nullable=False, default='pool')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    versions = db.relationship('PhotoVersion', backref='group', cascade='all, delete-orphan', order_by='PhotoVersion.created_at')
    tags = db.relationship('Tag', secondary=group_tags, backref='photos')
    campaigns = db.relationship('Campaign', backref='group', cascade='all, delete-orphan')

class PhotoVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('photo_group.id'), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(500), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class TagGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    tags = db.relationship('Tag', backref='tag_group')

class Tag(db.Model):
    @property
    def category_key(self):
        return f'{self.tag_group.name.casefold()}:{self.tag_group_id}' if self.tag_group else '~uncategorised'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    tag_group_id = db.Column(db.Integer, db.ForeignKey('tag_group.id'))

class Platform(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    accounts = db.relationship('SocialAccount', backref='platform')

class SocialAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platform.id'), nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    handle = db.Column(db.String(200), nullable=False)
    profile_url = db.Column(db.String(1000), default='')
    active = db.Column(db.Boolean, nullable=False, default=True)

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('photo_group.id'), nullable=False)
    version_id = db.Column(db.Integer, db.ForeignKey('photo_version.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    version = db.relationship('PhotoVersion')
    destinations = db.relationship('CampaignDestination', backref='campaign', cascade='all, delete-orphan')

class CampaignDestination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('social_account.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='planned')
    published_at = db.Column(db.DateTime)
    post_url = db.Column(db.String(1000), default='')
    account = db.relationship('SocialAccount')
    __table_args__ = (db.UniqueConstraint('campaign_id', 'account_id'),)

STATES = ('pool', 'staging', 'never_post', 'final')

def create_app(config=None):
    app = Flask(__name__)
    root = Path(app.root_path)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY'), SQLALCHEMY_DATABASE_URI='sqlite:///' + str(root / 'data' / 'app.db'), SQLALCHEMY_TRACK_MODIFICATIONS=False, MEDIA_ROOT=str(root / 'media'), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true').lower() == 'true', MAX_CONTENT_LENGTH=512 * 1024 * 1024)
    if config: app.config.update(config)
    if not app.config['SECRET_KEY']: raise RuntimeError('SECRET_KEY is required')
    if os.getenv('TRUST_PROXY', 'false').lower() == 'true': app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    db.init_app(app)
    Migrate(app, db, directory=str(root / 'migrations'), compare_type=True, render_as_batch=True)
    register_database_commands(app, db)
    oauth = OAuth(app)
    oauth.register('oidc', client_id=os.getenv('OIDC_CLIENT_ID'), client_secret=os.getenv('OIDC_CLIENT_SECRET'), server_metadata_url=os.getenv('OIDC_ISSUER', '').rstrip('/') + '/.well-known/openid-configuration', client_kwargs={'scope': 'openid profile email', 'code_challenge_method': 'S256'})
    app.extensions['oidc_client'] = oauth.oidc
    Path(app.config['MEDIA_ROOT']).mkdir(parents=True, exist_ok=True)
    with app.app_context():
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        if uri.startswith('sqlite:///') and uri != 'sqlite:///:memory:':
            path = Path(uri.removeprefix('sqlite:///'))
            path.parent.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def protect():
        if request.endpoint in ('login', 'callback', 'static'): return
        allowed = {x.strip() for x in os.getenv('OIDC_ALLOWED_SUBJECTS', '').split(',') if x.strip()}
        if not session.get('sub') or (allowed and session['sub'] not in allowed):
            session.clear()
            return redirect(url_for('login'))
        if request.method == 'POST' and (not session.get('csrf') or request.form.get('csrf_token') != session['csrf']): abort(400)
        if request.method == 'GET' and request.endpoint and request.endpoint != 'media' and not session.get('profile_loaded') and session.get('display_name') in (None, 'User'):
            session['profile_return_to'] = request.full_path.rstrip('?')
            return redirect(url_for('login'))

    @app.before_request
    def lock_library_writes():
        # Shared across threads and workers; hold until commit/rollback, including deletions.
        if request.method == 'POST' and request.endpoint not in ('login', 'callback', 'static'):
            lock = FileLock(str(Path(app.config['MEDIA_ROOT']) / '.library-write.lock'))
            lock.acquire()
            g.library_write_lock = lock
            g.upload_paths = []

    @app.teardown_request
    def release_library_write(error):
        lock = g.pop('library_write_lock', None)
        if lock is not None:
            try:
                db.session.rollback()
                for path in g.pop('upload_paths', []):
                    path.unlink(missing_ok=True)
                    try:
                        path.parent.rmdir()
                    except OSError:
                        pass
            finally:
                lock.release()

    def commit_uploads():
        db.session.commit()
        g.upload_paths = []

    @app.errorhandler(HTTPException)
    def http_error(error):
        return render_template('error.html', error=error), error.code

    @app.context_processor
    def account_context():
        subject = session.get('sub')
        if not subject:
            return {'current_user': None}
        identity = os.getenv('OIDC_ISSUER', '').rstrip('/') + '\0' + subject
        key = app.config['SECRET_KEY']
        if isinstance(key, str):
            key = key.encode('utf-8')
        seed = hmac.new(key, identity.encode('utf-8'), hashlib.sha256).hexdigest()
        return {'current_user': {
            'name': session.get('display_name') or 'User',
            'avatar_url': 'https://api.dicebear.com/10.x/notionists/svg?' + urlencode({'seed': seed})
        }}

    @app.context_processor
    def common(): return {'states': STATES, 'csrf_token': session.get('csrf', ''), 'state_help': {'pool': 'New imports, ready to review and organise.', 'staging': 'Selected photos being prepared for posting.', 'never_post': 'Photos kept in your library, excluded from new campaigns.', 'final': 'Photos with a recorded publication.'}}

    @app.get('/login')
    def login(): return app.extensions['oidc_client'].authorize_redirect(url_for('callback', _external=True))

    @app.get('/auth/callback')
    def callback():
        try:
            token = app.extensions['oidc_client'].authorize_access_token()
            userinfo = token.get('userinfo', {})
            sub = userinfo.get('sub')
        except Exception:
            abort(401, 'Authentication failed')
        allowed = {x.strip() for x in os.getenv('OIDC_ALLOWED_SUBJECTS', '').split(',') if x.strip()}
        return_to = session.get('profile_return_to')
        session.clear()
        if not sub or (allowed and sub not in allowed): abort(403, 'Identity is not allowed')
        session['sub'] = sub
        full_name = ' '.join(value.strip() for value in (userinfo.get('given_name'), userinfo.get('family_name')) if isinstance(value, str) and value.strip())
        candidates = (userinfo.get('display_name'), userinfo.get('name'), full_name, userinfo.get('preferred_username'))
        session['display_name'] = next((value.strip()[:120] for value in candidates if isinstance(value, str) and value.strip()), 'User')
        session['profile_loaded'] = True
        session['csrf'] = uuid.uuid4().hex
        return redirect(return_to if isinstance(return_to, str) and return_to.startswith('/') and not return_to.startswith('//') else url_for('dashboard'))

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    def dashboard():
        return render_template('dashboard.html', counts={s: PhotoGroup.query.filter_by(state=s).count() for s in STATES}, recent=PhotoGroup.query.order_by(PhotoGroup.created_at.desc(), PhotoGroup.id.desc()).limit(5).all(), planned=CampaignDestination.query.filter_by(status='planned').count())

    def store(file, group, label):
        filename = secure_filename(file.filename or '')
        if not filename: raise ValueError('Please choose an image file')
        if Path(filename).suffix.lower() not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif'}: raise ValueError('Supported images: JPG, PNG, GIF, WebP and AVIF')
        # No schema change: include every existing managed version on first upload.
        def digest(stream):
            result = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                result.update(chunk)
            return result.digest()

        if not hasattr(g, 'library_hashes'):
            g.library_hashes = set()
            for version in PhotoVersion.query.all():
                existing = Path(app.config['MEDIA_ROOT']) / version.stored_path
                if existing.is_file():
                    with existing.open('rb') as source:
                        g.library_hashes.add(digest(source))
        file.stream.seek(0)
        fingerprint = digest(file.stream)
        file.stream.seek(0)
        if fingerprint in g.library_hashes:
            raise ValueError('Duplicate skipped: this image already exists in the library.')
        folder = Path(app.config['MEDIA_ROOT']) / str(group.id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (uuid.uuid4().hex + Path(filename).suffix.lower())
        g.upload_paths.append(path)
        file.save(path)
        g.library_hashes.add(fingerprint)
        db.session.add(PhotoVersion(group=group, label=label or 'Original', original_filename=file.filename, stored_path=f'{group.id}/{path.name}'))

    @app.route('/import', methods=['GET', 'POST'])
    def import_photos():
        if request.method == 'POST':
            files = [f for f in request.files.getlist('files') if f.filename]
            if not files: flash('Choose at least one image.')
            else:
                imported = 0
                for f in files:
                    try:
                        group = PhotoGroup(state='pool'); db.session.add(group); db.session.flush()
                        store(f, group, 'Original')
                        imported += 1
                    except ValueError as e:
                        db.session.delete(group); flash(f'{f.filename}: {e}')
                commit_uploads(); flash(f'Imported {imported} photo groups into Pool.')
                return redirect(url_for('gallery', state='pool'))
        return render_template('import.html')

    @app.get('/media/<path:path>')
    def media(path): return send_from_directory(app.config['MEDIA_ROOT'], path)

    @app.get('/gallery/<state>')
    def gallery(state):
        if state not in (*STATES, 'all'): abort(404)
        q = PhotoGroup.query
        if state != 'all': q = q.filter_by(state=state)
        search = request.args.get('q', '').strip()
        if search:
            q = q.filter(PhotoGroup.versions.any(PhotoVersion.original_filename.icontains(search, autoescape=True)))
        for tag_id in request.args.getlist('tag', type=int): q = q.filter(PhotoGroup.tags.any(Tag.id == tag_id))
        selected_group = request.args.get('tag_group', '')
        if selected_group == 'ungrouped':
            q = q.filter(PhotoGroup.tags.any(Tag.tag_group_id.is_(None)))
        elif selected_group:
            try:
                group_id = int(selected_group)
            except ValueError:
                abort(400, 'Invalid tag group.')
            q = q.filter(PhotoGroup.tags.any(Tag.tag_group_id == group_id))
        platform = request.args.get('platform', type=int); account = request.args.get('account', type=int); status = request.args.get('status', '')
        start = request.args.get('start', ''); end = request.args.get('end', '')
        if status and status not in ('planned', 'published'): abort(400)
        if platform or account or status or start or end:
            dq = db.session.query(CampaignDestination.id).join(Campaign).join(SocialAccount).filter(Campaign.group_id == PhotoGroup.id)
            if platform: dq = dq.filter(SocialAccount.platform_id == platform)
            if account: dq = dq.filter(CampaignDestination.account_id == account)
            if status: dq = dq.filter(CampaignDestination.status == status)
            try:
                if start: dq = dq.filter(CampaignDestination.published_at >= datetime.fromisoformat(start))
                if end:
                    from datetime import timedelta
                    dq = dq.filter(CampaignDestination.published_at < datetime.fromisoformat(end) + timedelta(days=1))
            except ValueError: abort(400, 'Invalid date')
            q = q.filter(dq.exists())
        return render_template('gallery.html', state=state, tag_groups=TagGroup.query.order_by(TagGroup.name).all(), photos=q.order_by(PhotoGroup.created_at.asc() if request.args.get('sort') == 'oldest' else PhotoGroup.created_at.desc()).all(), tags=Tag.query.order_by(Tag.name).all(), platforms=Platform.query.order_by(Platform.name).all(), accounts=SocialAccount.query.order_by(SocialAccount.display_name).all())

    def apply_group_tags(photo):
        if request.form.get('new_tags', '').strip():
            abort(400, 'Tags can only be created on the Tags page.')
        raw_ids = request.form.getlist('tag')
        try:
            ids = {int(value) for value in raw_ids}
        except ValueError:
            abort(400, 'Invalid tag selection.')
        selected = Tag.query.filter(Tag.id.in_(ids)).all()
        if len(selected) != len(ids):
            abort(400, 'A selected tag no longer exists.')
        photo.tags = selected

    @app.route('/pool/review', defaults={'id': None}, methods=['GET'])
    @app.route('/pool/review/<int:id>', methods=['GET', 'POST'])
    def pool_review(id):
        queue = PhotoGroup.query.filter_by(state='pool').order_by(PhotoGroup.created_at, PhotoGroup.id).all()
        if id is None:
            if queue:
                return redirect(url_for('pool_review', id=queue[0].id))
            return render_template('review.html', photo=None, remaining=0)
        photo = db.get_or_404(PhotoGroup, id)
        if photo.state != 'pool':
            abort(409, 'This photo is no longer in Pool.')
        index = next((i for i, item in enumerate(queue) if item.id == photo.id), None)
        if index is None:
            abort(409, 'This photo is no longer in Pool.')
        selected_id = request.values.get('version_id', type=int)
        version = next((v for v in photo.versions if v.id == selected_id), None) if selected_id else (photo.versions[-1] if photo.versions else None)
        if selected_id and not version:
            abort(400, 'The version does not belong to this photo.')
        if request.method == 'POST':
            action = request.form.get('action')
            if action not in ('accept', 'deny', 'next', 'previous', 'save', 'preview', 'confirm_delete_group', 'confirm_delete_version'):
                abort(400)
            apply_group_tags(photo)
            if action in ('accept', 'deny'):
                target = 'staging' if action == 'accept' else 'never_post'
                # Conditional update prevents an old review tab from overwriting another decision.
                changed = db.session.query(PhotoGroup).filter_by(id=photo.id, state='pool').update({'state': target}, synchronize_session=False)
                if changed != 1:
                    db.session.rollback()
                    abort(409, 'This photo is no longer in Pool.')
            db.session.commit()
            if action == 'confirm_delete_group':
                return redirect(url_for('delete_group', id=photo.id, origin='review'))
            if action == 'confirm_delete_version':
                if not version:
                    abort(400, 'No version selected.')
                return redirect(url_for('delete_version', group_id=photo.id, version_id=version.id, origin='review'))
            if action in ('save', 'preview'):
                if action == 'save':
                    flash('Tags saved.')
                return redirect(url_for('pool_review', id=photo.id, version_id=version.id if version else None))
            if action in ('accept', 'deny'):
                queue.pop(index)
                next_photo = queue[index % len(queue)] if queue else None
            else:
                next_photo = queue[(index + (1 if action == 'next' else -1)) % len(queue)]
            return redirect(url_for('pool_review', id=next_photo.id) if next_photo else url_for('pool_review'))
        analysis = inspect_image(app.config['MEDIA_ROOT'], version.stored_path) if version else None
        return render_template('review.html', photo=photo, version=version, analysis=analysis,
                               position=index + 1, remaining=len(queue), tags=Tag.query.order_by(Tag.name).all(),
                               version_in_use=bool(version and Campaign.query.filter_by(version_id=version.id).first()))

    @app.route('/group/<int:id>', methods=['GET', 'POST'])
    def group(id):
        photo = db.get_or_404(PhotoGroup, id)
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'state':
                state = request.form.get('state')
                if state not in ('pool', 'staging', 'never_post'): abort(400)
                photo.state = state
                flash('Group moved to ' + state.replace('_', ' ').title() + '.')
            elif action == 'tags':
                apply_group_tags(photo)
                flash('Tags saved.')
            elif action == 'version':
                f = request.files.get('file')
                try: store(f, photo, request.form.get('label', '').strip() or 'Edit') if f else (_ for _ in ()).throw(ValueError('Choose an image.'))
                except ValueError as e: flash(str(e))
            else: abort(400)
            commit_uploads(); return redirect(url_for('group', id=id))
        return render_template('group.html', photo=photo, tags=Tag.query.order_by(Tag.name).all(),
                               used_version_ids={c.version_id for c in photo.campaigns})

    @app.post('/library/bulk')
    def bulk_edit():
        try:
            ids = {int(value) for value in request.form.getlist('photo_ids')}
        except ValueError:
            abort(400, 'Invalid photo selection.')
        if not ids or len(ids) > 500:
            abort(400, 'Select between 1 and 500 photo groups.')
        photos = PhotoGroup.query.filter(PhotoGroup.id.in_(ids)).order_by(PhotoGroup.id).all()
        if len(photos) != len(ids):
            abort(409, 'A selected photo group no longer exists.')
        return_state = request.form.get('return_state', 'all')
        if return_state not in (*STATES, 'all'):
            abort(400, 'Invalid gallery.')
        action = request.form.get('action')
        if action in ('edit', 'delete'):
            return render_template('bulk_edit.html', photos=photos, deleting=action == 'delete',
                                   return_state=return_state, tags=Tag.query.order_by(Tag.name).all())
        if action not in ('apply', 'confirm_delete'):
            abort(400)
        if any(request.form.get(f'state_before_{photo.id}') != photo.state for photo in photos):
            abort(409, 'A selected photo has changed state. Select the photos again.')
        if action == 'confirm_delete':
            if request.form.get('confirm') != 'delete':
                abort(400, 'Deletion confirmation required.')
            versions = [version for photo in photos for version in photo.versions]
            try:
                delete_with_media(db, photos, versions, app.config['MEDIA_ROOT'])
            except (MediaDeletionError, OSError) as error:
                abort(409, str(error))
            flash(f'Deleted {len(ids)} photo groups.')
        else:
            target = request.form.get('state', '')
            mode = request.form.get('tag_mode', 'keep')
            if target not in ('', 'pool', 'staging', 'never_post') or mode not in ('keep', 'add', 'remove', 'replace'):
                abort(400, 'Invalid bulk edit.')
            if request.form.get('new_tags', '').strip():
                abort(400, 'Tags can only be created on the Tags page.')
            try:
                tag_ids = {int(value) for value in request.form.getlist('tag')}
            except ValueError:
                abort(400, 'Invalid tag selection.')
            selected = Tag.query.filter(Tag.id.in_(tag_ids)).all()
            if len(selected) != len(tag_ids):
                abort(400, 'A selected tag no longer exists.')
            for photo in photos:
                if target:
                    changed = db.session.query(PhotoGroup).filter_by(id=photo.id, state=photo.state).update({'state': target}, synchronize_session=False)
                    if changed != 1:
                        db.session.rollback()
                        abort(409, 'A selected photo has changed state.')
                if mode == 'replace':
                    photo.tags = list(selected)
                elif mode == 'add':
                    photo.tags = list(photo.tags) + [tag for tag in selected if tag not in photo.tags]
                elif mode == 'remove':
                    photo.tags = [tag for tag in photo.tags if tag.id not in tag_ids]
            db.session.commit()
            flash(f'Updated {len(ids)} photo groups.')
        return redirect(url_for('gallery', state=return_state))

    def deletion_origin():
        value = request.form.get('origin', request.args.get('origin', 'workspace'))
        return 'review' if value == 'review' else 'workspace'

    @app.route('/group/<int:id>/delete', methods=['GET', 'POST'])
    def delete_group(id):
        photo = db.get_or_404(PhotoGroup, id)
        origin = deletion_origin()
        queue = PhotoGroup.query.filter_by(state='pool').order_by(PhotoGroup.created_at, PhotoGroup.id).all()
        index = next((i for i, item in enumerate(queue) if item.id == id), 0)
        others = [item.id for item in queue if item.id != id]
        next_id = others[index % len(others)] if others else None
        if request.method == 'POST':
            if request.form.get('confirm') != 'delete':
                abort(400, 'Deletion confirmation required.')
            previous_state = photo.state
            try:
                delete_with_media(db, photo, list(photo.versions), app.config['MEDIA_ROOT'])
            except (MediaDeletionError, OSError) as error:
                abort(409, str(error))
            flash('Photo group deleted.')
            if origin == 'review':
                return redirect(url_for('pool_review', id=next_id) if next_id else url_for('pool_review'))
            return redirect(url_for('gallery', state=previous_state))
        return render_template('confirm_delete.html', photo=photo, version=None, origin=origin)

    @app.route('/group/<int:group_id>/version/<int:version_id>/delete', methods=['GET', 'POST'])
    def delete_version(group_id, version_id):
        photo = db.get_or_404(PhotoGroup, group_id)
        version = db.get_or_404(PhotoVersion, version_id)
        if version.group_id != photo.id:
            abort(404)
        if len(photo.versions) <= 1:
            abort(409, 'The last version can only be removed by deleting its photo group.')
        if Campaign.query.filter_by(version_id=version.id).first():
            abort(409, 'This version is used by a campaign and cannot be deleted.')
        origin = deletion_origin()
        if request.method == 'POST':
            if request.form.get('confirm') != 'delete':
                abort(400, 'Deletion confirmation required.')
            try:
                delete_with_media(db, version, [version], app.config['MEDIA_ROOT'])
            except (MediaDeletionError, OSError) as error:
                abort(409, str(error))
            flash('Image version deleted.')
            return redirect(url_for('pool_review', id=photo.id) if origin == 'review' and photo.state == 'pool' else url_for('group', id=photo.id))
        return render_template('confirm_delete.html', photo=photo, version=version, origin=origin)

    @app.route('/campaign/<int:group_id>/new', methods=['GET', 'POST'])
    @app.route('/campaign/edit/<int:campaign_id>', methods=['GET', 'POST'])
    def campaign(group_id=None, campaign_id=None):
        item = db.get_or_404(Campaign, campaign_id) if campaign_id else None
        photo = item.group if item else db.get_or_404(PhotoGroup, group_id)
        if not item and photo.state == 'never_post': abort(403, 'Move this group to Pool or Staging before creating a campaign.')
        if request.method == 'POST':
            version = db.session.get(PhotoVersion, request.form.get('version_id', type=int))
            name = request.form.get('name', '').strip()
            if not version or version.group_id != photo.id or not name: abort(400, 'A name and a version from this group are required')
            if not item: item = Campaign(group=photo, version=version, name=name); db.session.add(item)
            item.name = name; item.version = version
            selected = set(request.form.getlist('accounts', type=int))
            accounts = SocialAccount.query.filter(SocialAccount.id.in_(selected)).all()
            if len(accounts) != len(selected): abort(400)
            existing = {d.account_id: d for d in item.destinations}
            for d in list(item.destinations):
                if d.account_id not in selected: db.session.delete(d)
            for account in accounts:
                d = existing.get(account.id)
                if not d: d = CampaignDestination(account=account, campaign=item); db.session.add(d)
                status = request.form.get(f'status_{account.id}', 'planned')
                if status not in ('planned', 'published'): abort(400)
                d.status = status
                date = request.form.get(f'date_{account.id}', '').strip()
                try: d.published_at = datetime.fromisoformat(date) if date and status == 'published' else (datetime.utcnow() if status == 'published' else None)
                except ValueError: abort(400, 'Invalid publication date')
                d.post_url = request.form.get(f'url_{account.id}', '').strip()
                if status == 'published': photo.state = 'final'
            db.session.commit(); flash('Campaign saved.'); return redirect(url_for('group', id=photo.id))
        return render_template('campaign.html', photo=photo, item=item, accounts=SocialAccount.query.order_by(SocialAccount.display_name).all())

    @app.route('/tags', methods=['GET', 'POST'])
    def tags():
        if request.method == 'POST':
            action = request.form.get('action'); name = request.form.get('name', '').strip(); id = request.form.get('id', type=int)
            if action in ('save_group', 'save_tag') and not name: abort(400)
            if action == 'save_group':
                obj = db.get_or_404(TagGroup, id) if id else TagGroup(); obj.name = name; db.session.add(obj)
            elif action == 'save_tag':
                obj = db.get_or_404(Tag, id) if id else Tag(); obj.name = name
                group_id = request.form.get('tag_group_id', type=int)
                if group_id: db.get_or_404(TagGroup, group_id)
                obj.tag_group_id = group_id; db.session.add(obj)
            elif action == 'delete_tag': db.session.delete(db.get_or_404(Tag, id))
            elif action == 'delete_group':
                obj = db.get_or_404(TagGroup, id)
                for tag in obj.tags: tag.tag_group_id = None
                db.session.delete(obj)
            else: abort(400)
            try: db.session.commit()
            except Exception: db.session.rollback(); flash('Could not save. Names of tag groups must be unique.')
            return redirect(url_for('tags'))
        return render_template('tags.html', groups=TagGroup.query.order_by(TagGroup.name).all(), tags=Tag.query.order_by(Tag.name).all())

    @app.route('/accounts', methods=['GET', 'POST'])
    def accounts():
        if request.method == 'POST':
            action = request.form.get('action'); id = request.form.get('id', type=int)
            if action == 'platform':
                name = request.form.get('name', '').strip()
                if not name: abort(400)
                obj = db.get_or_404(Platform, id) if id else Platform(); obj.name = name; db.session.add(obj)
            elif action == 'account':
                name = request.form.get('display_name', '').strip(); handle = request.form.get('handle', '').strip(); platform_id = request.form.get('platform_id', type=int)
                if not name or not handle or not platform_id: abort(400)
                db.get_or_404(Platform, platform_id)
                obj = db.get_or_404(SocialAccount, id) if id else SocialAccount()
                obj.display_name = name; obj.handle = handle; obj.platform_id = platform_id; obj.profile_url = request.form.get('profile_url', '').strip(); obj.active = 'active' in request.form; db.session.add(obj)
            else: abort(400)
            try: db.session.commit()
            except Exception: db.session.rollback(); flash('Could not save. Platform names must be unique.')
            return redirect(url_for('accounts'))
        return render_template('accounts.html', platforms=Platform.query.order_by(Platform.name).all(), accounts=SocialAccount.query.order_by(SocialAccount.display_name).all())
    return app

app = create_app()




