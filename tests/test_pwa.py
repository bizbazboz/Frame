import io
from PIL import Image

from test_app import app, client, post


def test_manifest_worker_and_icons_are_public(app):
    anonymous = app.test_client()
    response = anonymous.get('/manifest.webmanifest')
    assert response.status_code == 200
    assert response.mimetype == 'application/manifest+json'
    manifest = response.get_json()
    assert manifest['id'] == manifest['start_url'] == manifest['scope'] == '/'
    assert manifest['display'] == 'standalone'
    assert manifest['name'] == 'Frame'
    assert {'192x192', '512x512'} <= {icon['sizes'] for icon in manifest['icons']}
    assert any(icon['purpose'] == 'maskable' for icon in manifest['icons'])
    for icon in manifest['icons']:
        image_response = anonymous.get(icon['src'])
        assert image_response.status_code == 200
        with Image.open(io.BytesIO(image_response.data)) as image:
            assert image.format == 'PNG'
            assert image.size == tuple(map(int, icon['sizes'].split('x')))
            if icon['purpose'] == 'maskable':
                assert image.getextrema()[3] == (255, 255)
    worker = anonymous.get('/service-worker.js')
    assert worker.status_code == 200
    assert worker.mimetype == 'application/javascript'
    assert worker.headers['Service-Worker-Allowed'] == '/'
    assert worker.headers['Cache-Control'] == 'no-cache'
    assert anonymous.get('/static/offline.html').status_code == 200
    with anonymous.session_transaction() as session:
        assert not session.get('sub')


def test_pwa_does_not_relax_library_authentication_or_cache_policy(client, app):
    page = client.get('/')
    assert b'rel="manifest"' in page.data
    assert b'apple-touch-icon' in page.data
    assert b'data-pwa-install hidden' in page.data
    assert b'/static/pwa.js' in page.data
    assert 'no-store' in page.headers['Cache-Control']
    post(client, '/import', files=(io.BytesIO(b'private-image'), 'private.png'))
    from app import PhotoVersion
    with app.app_context():
        path = PhotoVersion.query.one().stored_path
    assert 'no-store' in client.get('/media/'+path).headers['Cache-Control']
    assert 'no-store' in post(client, '/logout').headers['Cache-Control']
    for path in ['/', '/import', '/gallery/all', '/media/'+path]:
        denied = client.get(path)
        assert denied.status_code == 302
        assert denied.location.endswith('/login')
        assert 'no-store' in denied.headers['Cache-Control']
    assert client.get('/manifest.webmanifest').status_code == 200
    assert client.get('/service-worker.js').status_code == 200
