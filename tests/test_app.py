import io
import os
from pathlib import Path

import pytest
from flask_migrate import upgrade

os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ['OIDC_ALLOWED_SUBJECTS'] = 'allowed'
from app import create_app, db, PhotoGroup, PhotoVersion, CampaignDestination

@pytest.fixture
def app(tmp_path):
    application = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'db.sqlite'), 'MEDIA_ROOT': str(tmp_path / 'media'), 'SESSION_COOKIE_SECURE': False})
    with application.app_context():
        upgrade()
    return application

@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s['sub'] = 'allowed'; s['csrf'] = 'token'; s['profile_loaded'] = True
    return client

def post(client, url, **data):
    return client.post(url, data={'csrf_token': 'token', **data})

def test_schema_restart(tmp_path):
    config = {'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'db.sqlite'), 'MEDIA_ROOT': str(tmp_path / 'media')}
    first = create_app(config)
    with first.app_context():
        upgrade()
        db.session.add(PhotoGroup(state='pool', project_id=1)); db.session.commit()
    second = create_app(config)
    with second.app_context(): assert PhotoGroup.query.count() == 1

def test_oidc_and_protection(app, monkeypatch):
    client = app.test_client()
    assert client.get('/').status_code == 302
    class OIDC:
        def authorize_redirect(self, uri): return 'login redirect'
        def authorize_access_token(self): return {'userinfo': {'sub': self.sub}}
    oidc = OIDC(); oidc.sub = 'other'; app.extensions['oidc_client'] = oidc
    assert client.get('/login').data == b'login redirect'
    assert client.get('/auth/callback').status_code == 403
    oidc.sub = 'allowed'; assert client.get('/auth/callback').status_code == 302
    assert client.get('/').status_code == 200
    with client.session_transaction() as s: csrf = s['csrf']
    assert client.post('/logout', data={'csrf_token': csrf}).status_code == 302
    assert client.get('/').status_code == 302

def test_library_and_campaign(client, app):
    result = post(client, '/import', files=[(io.BytesIO(b'first'), 'one.jpg'), (io.BytesIO(b'second'), 'two.png')])
    assert result.status_code == 302
    with app.app_context():
        assert PhotoGroup.query.count() == 2
        version = PhotoVersion.query.first(); gid = version.group_id; vid = version.id
        assert (Path(app.config['MEDIA_ROOT']) / version.stored_path).read_bytes() == b'first'
    assert post(client, f'/group/{gid}', action='version', label='Edit', file=(io.BytesIO(b'edit'), 'edit.jpg')).status_code == 302
    assert post(client, f'/group/{gid}', action='state', state='never_post').status_code == 302
    assert client.get(f'/campaign/{gid}/new').status_code == 403
    post(client, f'/group/{gid}', action='state', state='staging')
    post(client, '/tags', action='save_group', name='Safety')
    post(client, '/tags', action='save_tag', name='Safe', tag_group_id='1')
    post(client, '/tags', action='save_tag', name='landscape')
    post(client, f'/group/{gid}', action='tags', tag=['1','2'])
    post(client, '/accounts', action='platform', name='Network')
    for name in ('One', 'Two'):
        post(client, '/accounts', action='account', platform_id='1', display_name=name, handle='@' + name, active='on')
    result = post(client, f'/campaign/{gid}/new', name='Launch', version_id=str(vid), accounts=['1','2'], status_1='published', date_1='2026-01-02T10:00', url_1='https://example.com/post', status_2='planned')
    assert result.status_code == 302
    with app.app_context():
        assert db.session.get(PhotoGroup, gid).state == 'final'
        assert CampaignDestination.query.count() == 2
    assert b'one.jpg' in client.get('/gallery/final?tag=1&platform=1&account=1&status=published&start=2026-01-02&end=2026-01-02').data
    assert b'one.jpg' not in client.get('/gallery/final?account=2&status=published').data
    assert b'one.jpg' in client.get('/gallery/all?q=ONE').data
    assert b'two.png' not in client.get('/gallery/all?q=ONE').data
    assert b'one.jpg' not in client.get('/gallery/all?q=%25').data
    for url in ('/', '/tags', '/accounts', '/import', f'/group/{gid}', '/campaign/edit/1', '/gallery/all'):
        assert client.get(url).status_code == 200

def test_login_uses_pkce(app, monkeypatch):
    from urllib.parse import urlparse, parse_qs
    oidc = app.extensions['oidc_client']
    oidc.server_metadata.update({'authorization_endpoint': 'https://id.example/authorize', 'issuer': 'https://id.example'})
    monkeypatch.setattr(oidc, 'load_server_metadata', lambda: oidc.server_metadata)
    response = app.test_client().get('/login')
    params = parse_qs(urlparse(response.location).query)
    assert params['code_challenge_method'] == ['S256']
    assert params['redirect_uri'] == ['http://localhost/auth/callback']
    assert params['code_challenge']
    assert 'openid' in params['scope'][0].split()


def test_empty_allowlist_accepts_authenticated_users(app, monkeypatch):
    monkeypatch.setenv('OIDC_ALLOWED_SUBJECTS', ' , ')
    class OIDC:
        def authorize_access_token(self): return {'userinfo': {'sub': 'another-user'}}
    app.extensions['oidc_client'] = OIDC()
    client = app.test_client()
    assert client.get('/').status_code == 302
    assert client.get('/auth/callback').status_code == 302
    assert client.get('/').status_code == 200
    class MissingSubject:
        def authorize_access_token(self): return {'userinfo': {}}
    app.extensions['oidc_client'] = MissingSubject()
    assert client.get('/auth/callback').status_code == 403
