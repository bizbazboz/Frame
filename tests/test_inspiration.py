from urllib.parse import urlsplit
import pytest

from app import db, InspirationLink, Project
from inspiration import parse_inspiration_url
from test_app import app, client, post


@pytest.mark.parametrize('url,provider,canonical', [
    ('https://www.instagram.com/p/AbCd_123/?igsh=test#x','instagram','https://www.instagram.com/p/AbCd_123/'),
    ('https://instagram.com/reel/AbCd_123','instagram','https://www.instagram.com/reel/AbCd_123/'),
    ('https://www.instagram.com/artist/reel/AbCd_123/','instagram','https://www.instagram.com/reel/AbCd_123/'),
    ('http://old.reddit.com/r/Pics/comments/abc123/a_title/?utm_source=test','reddit','https://www.reddit.com/r/pics/comments/abc123/'),
    ('https://reddit.com/r/pics/comments/abc123/a_title/def456/','reddit','https://www.reddit.com/r/pics/comments/abc123/_/def456/'),
])
def test_supported_links_are_normalized(url, provider, canonical):
    kind, saved, embed = parse_inspiration_url(url)
    assert kind == provider and saved == canonical
    assert urlsplit(embed).hostname in ('www.instagram.com','embed.reddit.com')
    assert urlsplit(embed).scheme == 'https'


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'https://instagram.com.evil.test/p/abc123/',
    'https://www.instagram.com@127.0.0.1/p/abc123/',
    'https://evil@www.instagram.com/p/abc123/', 'http://127.0.0.1:8000/',
    'https://www.instagram.com:444/p/abc123/', 'https://www.instagram.com/profile/',
    'https://www.reddit.com/r/pics/', 'https://www.instagram.com/p/abc123/\n',
    'https://www.instagram.com/p/abc123/extra',
])
def test_unsupported_links_are_rejected(url):
    with pytest.raises(ValueError):
        parse_inspiration_url(url)


def test_add_cards_duplicates_and_delete(client, app):
    assert post(client, '/inspiration', url='https://www.instagram.com/p/AbCd_123/?igsh=one', title='<script>alert(1)</script>').status_code == 302
    assert post(client, '/inspiration', url='https://instagram.com/p/AbCd_123/?igsh=two').status_code == 302
    assert post(client, '/inspiration', url='https://www.reddit.com/r/pics/comments/abc123/example/', title='Lighting').status_code == 302
    with app.app_context():
        assert InspirationLink.query.count() == 2
    page = client.get('/inspiration')
    assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in page.data
    assert b'<script>alert(1)</script>' not in page.data
    assert b'https://embed.reddit.com/r/pics/comments/abc123/' in page.data
    assert b'https://www.instagram.com/p/AbCd_123/embed/captioned/' in page.data
    assert b'sandbox="allow-scripts allow-same-origin' in page.data
    assert b'Open post' in page.data and b'no-referrer' in page.data
    assert 'no-store' in page.headers['Cache-Control']
    assert client.post('/inspiration/1/delete').status_code == 400
    assert post(client, '/inspiration/1/delete').status_code == 302
    with app.app_context():
        assert InspirationLink.query.count() == 1
    assert post(client, '/inspiration', url='https://example.com').status_code == 400
    assert post(client, '/inspiration', url='https://instagram.com/p/abc123/', title='x'*161).status_code == 400


def test_project_context_and_project_deletion_preserve_links(client, app):
    link = 'https://www.instagram.com/p/AbCd_123/'
    post(client, '/inspiration?project=1', url=link, title='Main inspiration')
    post(client, '/projects', action='create', name='Client work')
    assert b'Main inspiration' not in client.get('/inspiration?project=2').data
    assert post(client, '/inspiration/1/delete?project=2').status_code == 404
    assert post(client, '/projects', action='delete', project_id='1').status_code == 409
    post(client, '/inspiration?project=2', url=link, title='Client inspiration')
    with app.app_context():
        assert InspirationLink.query.count() == 2
    post(client, '/inspiration', project_context='1', url='https://reddit.com/r/pics/comments/abc123/one/', title='Old tab')
    assert b'Old tab' in client.get('/inspiration?project=1').data
    assert b'Old tab' not in client.get('/inspiration?project=2').data
    assert b'/inspiration?project=2' in client.get('/').data
    assert post(client, '/inspiration?project=2', project_context='1', url=link).status_code == 400
    assert app.test_client().get('/inspiration').status_code == 302
