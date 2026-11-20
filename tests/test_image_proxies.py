import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app import db, PhotoVersion, Project
from image_proxies import encode_proxy, cached_proxy
from media_deletion import delete_with_media, MediaDeletionError
from test_app import app, client, post


def upload(client, payload=None):
    if payload is None:
        output = io.BytesIO()
        image = Image.new('RGB', (120, 80), '#ad2244')
        exif = Image.Exif()
        exif[274] = 6
        image.save(output, 'JPEG', exif=exif)
        payload = output.getvalue()
    assert post(client, '/import', files=(io.BytesIO(payload), 'photo.jpg')).status_code == 302
    return payload


def test_realistic_large_image_stays_within_budgets(tmp_path):
    source = tmp_path / 'large.png'
    Image.effect_noise((3200, 2400), 90).convert('RGB').save(source)
    before = source.read_bytes()
    for variant, edge, budget in [('display', 2400, 500_000), ('thumb', 640, 100_000)]:
        payload = encode_proxy(source, variant)
        assert len(payload) <= budget
        with Image.open(io.BytesIO(payload)) as preview:
            assert preview.format == 'WEBP'
            assert max(preview.size) <= edge
    assert source.read_bytes() == before


def test_preview_cache_orientation_original_and_scope(client, app):
    original = upload(client)
    response = client.get('/preview/1/display?project=1')
    assert response.status_code == 200 and response.mimetype == 'image/webp'
    assert 'no-store' in response.headers['Cache-Control']
    with Image.open(io.BytesIO(response.data)) as image:
        assert image.size == (80, 120)
        assert not image.getexif()
    with app.app_context():
        version = db.session.get(PhotoVersion, 1)
        path = cached_proxy(app.config['MEDIA_ROOT'], version, 'display')
        timestamp = path.stat().st_mtime_ns
        with patch('image_proxies.encode_proxy', side_effect=AssertionError('Must reuse cache')):
            assert client.get('/preview/1/display?project=1').data == response.data
        assert path.stat().st_mtime_ns == timestamp
        assert client.get('/media/' + version.stored_path + '?project=1').data == original
        db.session.add(Project(name='Other'))
        db.session.commit()
    assert client.get('/preview/1/display?project=2').status_code == 404
    assert app.test_client().get('/preview/1/display').status_code == 302
    assert client.get('/preview/1/invalid?project=1').status_code == 404
    assert b'/preview/1/thumb?project=1' in client.get('/gallery/all?project=1').data
    assert b'/preview/1/display?project=1' in client.get('/group/1?project=1').data


def test_corrupt_original_uses_small_placeholder(client):
    upload(client, b'not a decodable image')
    response = client.get('/preview/1/display')
    assert response.status_code == 200 and response.mimetype == 'image/svg+xml'
    assert b'Preview unavailable' in response.data
    assert len(response.data) < 1024


def test_cache_refresh_and_transactional_deletion(client, app):
    upload(client)
    client.get('/preview/1/display')
    client.get('/preview/1/thumb')
    with app.app_context():
        version = db.session.get(PhotoVersion, 1)
        root = Path(app.config['MEDIA_ROOT'])
        old = cached_proxy(root, version, 'thumb')
        Image.new('RGB', (70, 90), 'blue').save(root / version.stored_path)
        fresh = cached_proxy(root, version, 'thumb')
        assert fresh != old and not old.exists()
        cached = list((root / '.previews').glob('*.webp'))
        with patch.object(db.session, 'commit', side_effect=RuntimeError('database failed')):
            with pytest.raises(MediaDeletionError):
                delete_with_media(db, version.group, [version], root)
        assert all(path.exists() for path in cached)
    assert post(client, '/group/1/delete', confirm='delete').status_code == 302
    assert not list((root / '.previews').glob('*.webp'))
    assert client.get('/preview/1/thumb').status_code == 404
