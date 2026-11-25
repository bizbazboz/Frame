"""Manual, account-linked Reddit archive analytics. No credentials or background jobs."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from flask import abort, g, render_template, request
from sqlalchemy import func

API_URL = 'https://arctic-shift.photon-reddit.com/api/posts/search'
FIELDS = 'id,author,title,subreddit,created_utc,score,num_comments,over_18,retrieved_on'


class ArchiveError(Exception):
    def __init__(self, message, status=502, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


def reddit_username(value):
    value = value.strip()
    if value.startswith(('https://', 'http://')):
        parsed = urlsplit(value)
        if parsed.hostname not in ('reddit.com', 'www.reddit.com', 'old.reddit.com') or parsed.username or parsed.password:
            raise ValueError('Enter a Reddit username or Reddit profile URL.')
        value = parsed.path.strip('/')
    value = re.sub(r'^(?:/?u(?:ser)?/|@)', '', value, flags=re.I).rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,20}', value):
        raise ValueError('Reddit usernames must contain 3–20 letters, numbers, underscores or hyphens.')
    return value.lower()


def fetch_posts(username, before):
    params = {'author': username, 'sort': 'desc', 'limit': 100, 'fields': FIELDS}
    if before is not None:
        params['before'] = before
    try:
        with requests.get(API_URL, params=params, timeout=(5, 25), stream=True,
                          allow_redirects=False, headers={'User-Agent': 'Frame/1.0 (manual Reddit archive analytics)'}) as response:
            if response.status_code == 429:
                retry = response.headers.get('X-RateLimit-Reset', '60')
                try:
                    retry = max(1, min(3600, int(float(retry))))
                except (ValueError, OverflowError):
                    retry = 60
                raise ArchiveError(f'Arctic Shift rate limit reached. Retry in {retry} seconds.', 429, retry)
            if response.status_code != 200:
                raise ArchiveError('Arctic Shift is unavailable. Your saved posts and sync progress are unchanged.')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ArchiveError('Arctic Shift returned an oversized response.')
                chunks.append(chunk)
            payload = json.loads(b''.join(chunks))
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or len(payload['data']) > 100:
            raise ArchiveError('Arctic Shift returned an unexpected response.')
        return payload['data']
    except (requests.RequestException, ValueError) as error:
        raise ArchiveError('Could not read Arctic Shift. Your saved posts and sync progress are unchanged.') from error


def timestamp(value):
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).replace(tzinfo=None)


def metric(value):
    return None if value is None else max(-2147483648, min(2147483647, int(value)))


def normalize_posts(rows, username):
    normalized = []
    try:
        for row in rows:
            post_id = str(row['id']).removeprefix('t3_').lower()
            if not re.fullmatch(r'[a-z0-9]{1,20}', post_id) or str(row['author']).lower() != username:
                raise ValueError('Invalid identity')
            created = timestamp(row['created_utc'])
            if created is None:
                raise ValueError('Missing date')
            normalized.append(dict(reddit_id=post_id, username=username, title=str(row.get('title') or '')[:10000],
                subreddit=str(row['subreddit'])[:100], created_at=created, score=metric(row.get('score')),
                comments=metric(row.get('num_comments')), nsfw=row.get('over_18') is True,
                retrieved_at=timestamp(row.get('retrieved_on'))))
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
        raise ArchiveError('Arctic Shift returned invalid post data; this page was not saved.') from error
    return normalized


def register_reddit_analytics(app, db, Account, Platform, Post, Sync):
    def eligible_accounts():
        return Account.query.join(Platform).filter(func.lower(func.trim(Platform.name)) == 'reddit').order_by(Account.display_name).all()

    def username_for(account):
        try:
            return reddit_username(account.handle)
        except ValueError:
            return None

    @app.post('/reddit/accounts/<int:account_id>/sync')
    def reddit_sync(account_id):
        account = next((a for a in eligible_accounts() if a.id == account_id), None)
        if not account:
            abort(404)
        username = username_for(account)
        if not username or not account.active:
            return {'error': 'Set a valid Reddit handle and activate this account in Social accounts.'}, 400
        state = db.session.get(Sync, account.id)
        reset = request.form.get('reset') == '1' or not state or state.username != username
        if state and state.complete and not reset:
            return {'complete': True, 'count': Post.query.filter_by(account_id=account.id, username=username).count()}
        before = None if reset else state.before
        try:
            posts = normalize_posts(fetch_posts(username, before), username)
            oldest = min((int(p['created_at'].replace(tzinfo=timezone.utc).timestamp()) for p in posts), default=None)
            cursor = oldest + 1 if oldest is not None else before
            if len(posts) == 100 and before is not None and cursor >= before:
                raise ArchiveError('Archive pagination cannot advance past posts sharing one timestamp. Saved progress is preserved.', 409)
            if before is not None and any(int(p['created_at'].replace(tzinfo=timezone.utc).timestamp()) >= before for p in posts):
                raise ArchiveError('Arctic Shift returned posts outside the requested page; progress is preserved.')
            if not state:
                state = Sync(account_id=account.id, username=username)
                db.session.add(state)
            if state.username != username:
                Post.query.filter_by(account_id=account.id).delete()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for values in posts:
                item = Post.query.filter_by(account_id=account.id, reddit_id=values['reddit_id']).first()
                if not item:
                    item = Post(account_id=account.id)
                    db.session.add(item)
                for key, value in values.items():
                    setattr(item, key, value)
                item.synced_at = now
            state.username, state.before = username, cursor
            state.complete, state.synced_at = len(posts) < 100, now
            db.session.commit()
            return {'complete': state.complete, 'count': Post.query.filter_by(account_id=account.id, username=username).count(),
                    'synced_at': now.isoformat() + 'Z'}
        except ArchiveError as error:
            db.session.rollback()
            return {'error': str(error)}, error.status, ({'Retry-After': str(error.retry_after)} if error.retry_after else {})

    @app.get('/reddit')
    def reddit_analytics():
        accounts = eligible_accounts()
        requested = request.args.get('account', type=int)
        if request.args.get('account') and requested is None:
            abort(400, 'Invalid account.')
        selected = next((a for a in accounts if a.id == requested), None) if requested else (accounts[0] if accounts else None)
        if requested and not selected:
            abort(404)
        username = username_for(selected) if selected else None
        state = db.session.get(Sync, selected.id) if selected else None
        if state and state.username != username:
            state = None
        query = Post.query.filter_by(account_id=selected.id, username=username) if selected and username else Post.query.filter(db.false())
        subreddit = request.args.get('subreddit', '').strip().removeprefix('r/')
        title = request.args.get('q', '').strip()
        subreddits = [row[0] for row in query.with_entities(Post.subreddit).distinct().order_by(Post.subreddit).all()]
        if subreddit:
            query = query.filter(func.lower(Post.subreddit) == subreddit.lower())
        if title:
            query = query.filter(Post.title.icontains(title, autoescape=True))
        for key, column in [('min_score', Post.score), ('min_comments', Post.comments)]:
            value = request.args.get(key, '').strip()
            if value:
                try:
                    number = int(value)
                    if not -2147483648 <= number <= 2147483647:
                        raise ValueError()
                except ValueError:
                    abort(400, 'Invalid numeric filter.')
                query = query.filter(column >= number)
        for key in ('start', 'end'):
            value = request.args.get(key, '')
            if value:
                try:
                    date = datetime.strptime(value, '%Y-%m-%d')
                    query = query.filter(Post.created_at >= date) if key == 'start' else query.filter(Post.created_at < date + timedelta(days=1))
                except (ValueError, OverflowError):
                    abort(400, 'Invalid date filter.')
        nsfw = request.args.get('nsfw', '')
        if nsfw not in ('', 'yes', 'no'):
            abort(400)
        if nsfw:
            query = query.filter(Post.nsfw == (nsfw == 'yes'))
        orders = {'score': Post.score.desc().nullslast(), 'comments': Post.comments.desc().nullslast(),
                  'newest': Post.created_at.desc(), 'oldest': Post.created_at.asc()}
        sort = request.args.get('sort', 'score')
        if sort not in orders:
            abort(400)
        summary = query.with_entities(func.count(Post.id), func.sum(Post.score), func.avg(Post.score), func.sum(Post.comments)).one()
        communities = query.with_entities(Post.subreddit, func.count(Post.id).label('posts'),
            func.sum(Post.score).label('score'), func.avg(Post.score).label('average')).group_by(Post.subreddit).order_by(func.sum(Post.score).desc()).limit(8).all()
        pagination = query.order_by(orders[sort], Post.reddit_id).paginate(per_page=50, max_per_page=50, error_out=False)
        from flask import url_for
        def page_url(page):
            values = request.args.to_dict()
            values['page'] = page
            return url_for('reddit_analytics', **values)
        return render_template('reddit.html', accounts=accounts, selected=selected, username=username, sync=state,
            posts=pagination.items, pagination=pagination, summary=summary, communities=communities,
            subreddits=subreddits, page_url=page_url, sort=sort)
