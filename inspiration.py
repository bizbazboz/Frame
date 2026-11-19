"""Project inspiration bookmarks with isolated native platform embeds."""
import re
from urllib.parse import urlsplit
from flask import abort, flash, g, redirect, render_template, request, url_for


def parse_inspiration_url(value):
    if any(ord(char) < 32 for char in value):
        raise ValueError('Enter a valid Reddit or Instagram link.')
    value = value.strip()
    if not value or len(value) > 2048:
        raise ValueError('Enter a Reddit post or Instagram post/reel link.')
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or url.username or url.password or url.port not in (None, 80, 443):
            raise ValueError()
        host = (url.hostname or '').lower()
    except ValueError:
        raise ValueError('Enter a valid Reddit or Instagram link.') from None
    if host in ('instagram.com', 'www.instagram.com', 'm.instagram.com'):
        match = re.fullmatch(r'/(?:(?:[A-Za-z0-9._]+)/)?(p|reel|tv)/([A-Za-z0-9_-]{3,64})/?', url.path)
        if match:
            kind, shortcode = match.groups()
            canonical = f'https://www.instagram.com/{kind}/{shortcode}/'
            return 'instagram', canonical, canonical + 'embed/captioned/'
    elif host in ('reddit.com', 'www.reddit.com', 'old.reddit.com', 'new.reddit.com', 'np.reddit.com', 'm.reddit.com'):
        match = re.fullmatch(r'/r/([A-Za-z0-9_]{2,30})/comments/([A-Za-z0-9]+)(?:/[^/]+)?(?:/([A-Za-z0-9]+))?/?', url.path)
        if match:
            subreddit, post, comment = match.groups()
            path = f'/r/{subreddit.lower()}/comments/{post.lower()}/'
            if comment:
                path += f'_/{comment.lower()}/'
            canonical = 'https://www.reddit.com' + path
            return 'reddit', canonical, 'https://embed.reddit.com' + path + '?theme=dark'
    raise ValueError('Use a full Reddit post link or an Instagram post/reel link.')


def register_inspiration(app, db, InspirationLink):
    @app.route('/inspiration', methods=['GET', 'POST'])
    def inspiration():
        status = 200
        if request.method == 'POST':
            try:
                provider, canonical, _ = parse_inspiration_url(request.form.get('url', ''))
                title = request.form.get('title', '').strip()
                if len(title) > 160:
                    raise ValueError('Titles must be 160 characters or fewer.')
            except ValueError as error:
                flash(str(error))
                status = 400
            else:
                existing = InspirationLink.query.filter_by(project_id=g.project.id, url=canonical).first()
                if existing:
                    flash('This link is already saved in this project.')
                else:
                    db.session.add(InspirationLink(project_id=g.project.id, provider=provider, url=canonical, title=title))
                    db.session.commit()
                return redirect(url_for('inspiration'))
        entries = InspirationLink.query.filter_by(project_id=g.project.id).order_by(InspirationLink.created_at.desc(), InspirationLink.id.desc()).all()
        return render_template('inspiration.html', entries=entries), status

    @app.post('/inspiration/<int:id>/delete')
    def delete_inspiration(id):
        item = InspirationLink.query.filter_by(id=id, project_id=g.project.id).first_or_404()
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('inspiration'))
