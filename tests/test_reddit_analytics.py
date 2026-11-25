import json
from unittest.mock import patch, Mock

from app import db, RedditPost, RedditSync
from reddit_analytics import fetch_posts, ArchiveError, reddit_username
from test_app import app, client, post
import pytest


def account(client, name='artist_one'):
    post(client, '/accounts', action='platform', name='Reddit')
    response = post(client, '/accounts', action='account', platform_id='1', display_name=name, handle='u/' + name, active='on')
    assert response.status_code == 302


def row(id='abc', **values):
    return {'id': id, 'author': 'artist_one', 'title': 'Golden hour', 'subreddit': 'portraits',
            'created_utc': 1700000000, 'score': 120, 'num_comments': 8, 'over_18': False,
            'retrieved_on': 1700200000, **values}


def sync(client, rows, **data):
    with patch('reddit_analytics.fetch_posts', return_value=rows):
        return post(client, '/reddit/accounts/1/sync', **data)


def test_empty_accounts_and_protection(client, app):
    assert b'No Reddit accounts' in client.get('/reddit').data
    assert app.test_client().get('/reddit').status_code == 302
    account(client)
    assert b'Reddit analytics' in client.get('/accounts').data
    assert client.post('/reddit/accounts/1/sync').status_code == 400
    assert post(client, '/reddit/accounts/999/sync').status_code == 404
    post(client, '/accounts', action='account', id='1', platform_id='1', display_name='Inactive', handle='artist_one')
    assert sync(client, []).status_code == 400
    assert post(client, '/accounts', action='account', platform_id='1', display_name='Bad', handle='invalid/url', active='on').status_code == 400


def test_stats_filters_rankings_and_unknown_metrics(client, app):
    account(client)
    rows = [row(), row('def', title='<script>alert(1)</script>', subreddit='street', score=900, num_comments=4, over_18=True),
            row('ghi', title='Old title', created_utc=1600000000, score=None, num_comments=None)]
    result = sync(client, rows)
    assert result.status_code == 200 and result.json['count'] == 3 and result.json['complete']
    page = client.get('/reddit').data
    assert b'&lt;script&gt;' in page and b'<script>alert' not in page
    assert page.index(b'&lt;script&gt;') < page.index(b'Golden hour')
    assert b'900' in page and b'Top subreddits' in page and b'Arctic Shift' in page
    filtered = client.get('/reddit?subreddit=portraits&min_score=100&min_comments=5&start=2023-11-14&end=2023-11-14&nsfw=no&q=Golden&sort=comments').data
    assert b'Golden hour' in filtered and b'&lt;script&gt;' not in filtered and b'Old title' not in filtered
    assert b'Golden hour' not in client.get('/reddit?nsfw=yes').data
    for query in ('min_score=nan', 'start=invalid', 'sort=invalid', 'account=bad', 'account=99'):
        assert client.get('/reddit?' + query).status_code in (400, 404)
    with app.app_context():
        assert RedditPost.query.count() == 3
        assert db.session.get(RedditSync, 1).complete


def test_sync_resume_overlap_refresh_and_account_change(client, app):
    account(client)
    rows = [row(format(n + 1000, 'x'), created_utc=1700000000 - n) for n in range(100)]
    assert not sync(client, rows).json['complete']
    with patch('reddit_analytics.fetch_posts', return_value=[rows[-1], row('new', created_utc=1699999000)]) as fetch:
        response = post(client, '/reddit/accounts/1/sync')
        assert fetch.call_args.args == ('artist_one', 1699999902)
    assert response.json['complete'] and response.json['count'] == 101
    assert sync(client, [row(rows[0]['id'], score=999)], reset='1').json['count'] == 101
    with app.app_context():
        assert RedditPost.query.filter_by(reddit_id=rows[0]['id']).one().score == 999
    post(client, '/accounts', action='account', id='1', platform_id='1', display_name='Second identity', handle='artist_two', active='on')
    assert b'Golden hour' not in client.get('/reddit').data
    assert sync(client, [row('second', author='artist_two')]).json['count'] == 1
    with app.app_context():
        assert RedditPost.query.one().username == 'artist_two'


def test_failure_preserves_checkpoint_and_cached_metrics(client, app):
    account(client)
    sync(client, [row()])
    with app.app_context():
        previous = db.session.get(RedditSync, 1).synced_at
    with patch('reddit_analytics.fetch_posts', side_effect=ArchiveError('Rate limited', 429, 30)):
        failed = post(client, '/reddit/accounts/1/sync', reset='1')
        assert failed.status_code == 429 and failed.headers['Retry-After'] == '30'
    assert sync(client, [row(author='someone_else')], reset='1').status_code == 502
    with app.app_context():
        assert db.session.get(RedditSync, 1).synced_at == previous
        assert RedditPost.query.one().score == 120
    rows = [row(format(n + 1000, 'x')) for n in range(100)]
    assert sync(client, rows, reset='1').status_code == 200
    assert sync(client, rows).status_code == 409


def test_multiple_saved_accounts_remain_isolated(client, app):
    account(client)
    sync(client, [row()])
    post(client, '/accounts', action='account', platform_id='1', display_name='Second', handle='artist_two', active='on')
    with patch('reddit_analytics.fetch_posts', return_value=[row('xyz', author='artist_two', title='Second account only')]):
        assert post(client, '/reddit/accounts/2/sync').status_code == 200
    assert b'Golden hour' not in client.get('/reddit?account=2').data
    assert b'Second account only' not in client.get('/reddit?account=1').data
    assert b'Golden hour' in client.get('/reddit?account=1').data


def test_remote_client_timeout_limit_validation_and_usernames():
    assert reddit_username('https://www.reddit.com/user/Artist_One/') == 'artist_one'
    assert reddit_username('@Artist_One') == 'artist_one'
    for invalid in ('https://evil.test/user/artist_one', 'bad?name', 'a/b', '[deleted]'):
        with pytest.raises(ValueError):
            reddit_username(invalid)
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [json.dumps({'data': [row()]}).encode()]
    with patch('reddit_analytics.requests.get', return_value=response) as get:
        assert fetch_posts('artist_one', 123)[0]['id'] == 'abc'
        assert get.call_args.kwargs['params']['before'] == 123
        assert get.call_args.kwargs['allow_redirects'] is False
    response.iter_content.return_value = [b'x' * (4 * 1024 * 1024 + 1)]
    with patch('reddit_analytics.requests.get', return_value=response), pytest.raises(ArchiveError):
        fetch_posts('artist_one', None)
    response.status_code = 429
    response.headers = {'X-RateLimit-Reset': '12'}
    with patch('reddit_analytics.requests.get', return_value=response), pytest.raises(ArchiveError) as error:
        fetch_posts('artist_one', None)
    assert error.value.retry_after == 12
