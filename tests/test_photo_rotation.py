import hashlib
import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import db, PhotoVersion, PhotoVersionHash, Project
from test_app import app, client, post


def png():
    image = Image.new('RGB', (3,2))
    image.putdata([(255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255),(255,0,255)])
    exif = Image.Exif()
    exif[315] = 'Photographer'
    output = io.BytesIO()
    image.save(output, 'PNG', exif=exif)
    return output.getvalue()


def upload(client, payload=None, name='photo.png'):
    payload = payload or png()
    assert post(client, '/import', files=(io.BytesIO(payload),name)).status_code == 302
    return payload


def test_physical_rotation_download_cache_and_duplicate_history(client, app):
    before = upload(client)
    client.get('/preview/1/display')
    client.get('/preview/1/thumb')
    with app.app_context():
        path = Path(app.config['MEDIA_ROOT']) / db.session.get(PhotoVersion,1).stored_path
        stored = str(path)
    response = post(client, '/version/1/rotate', direction='right')
    assert response.status_code == 302 and 'version_id=1' in response.location
    assert str(path) == stored and path.read_bytes() != before
    with Image.open(path) as image:
        assert image.size == (2,3) and image.getpixel((0,0)) == (255,255,0)
        assert image.getexif()[315] == 'Photographer'
    with app.app_context():
        assert db.session.get(PhotoVersion,1).content_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert db.session.get(PhotoVersionHash,hashlib.sha256(before).hexdigest()).version_id == 1
        assert not list((Path(app.config['MEDIA_ROOT'])/'.previews').glob('1-*.webp'))
    download = client.get('/version/1/download')
    assert download.data == path.read_bytes()
    assert 'attachment' in download.headers['Content-Disposition'] and 'photo.png' in download.headers['Content-Disposition']
    download.close()
    with Image.open(io.BytesIO(client.get('/preview/1/display').data)) as preview:
        assert preview.size == (2,3)
    upload(client, before, 'old.png')
    upload(client, path.read_bytes(), 'new.png')
    with app.app_context():
        assert PhotoVersion.query.count() == 1
    assert post(client, '/version/1/rotate', direction='left').status_code == 302
    with Image.open(path) as image, Image.open(io.BytesIO(before)) as original:
        assert list(image.getdata()) == list(original.getdata())
    assert post(client, '/group/1/delete', confirm='delete').status_code == 302
    with app.app_context():
        assert PhotoVersionHash.query.count() == 0


def test_rotation_failure_restores_exact_original_and_hashes(client, app):
    before = upload(client)
    client.get('/preview/1/display')
    with app.app_context():
        path = Path(app.config['MEDIA_ROOT']) / db.session.get(PhotoVersion,1).stored_path
        old_hash = db.session.get(PhotoVersion,1).content_hash
    with patch.object(db.session, 'commit', side_effect=RuntimeError('commit failed')):
        response = post(client, '/version/1/rotate', direction='left')
    assert response.status_code == 409
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.*rotate*'))
    assert not list(path.parent.glob('.rotating-*'))
    with app.app_context():
        assert db.session.get(PhotoVersion,1).content_hash == old_hash
        assert PhotoVersionHash.query.count() == 0


def test_rotation_and_download_are_project_scoped_and_csrf_protected(client, app):
    before = upload(client)
    assert app.test_client().get('/version/1/download').status_code == 302
    assert client.post('/version/1/rotate', data={'direction':'left'}).status_code == 400
    assert post(client, '/version/1/rotate', direction='up').status_code == 400
    with app.app_context():
        db.session.add(Project(name='Other'))
        db.session.commit()
    assert post(client, '/version/1/rotate?project=2', direction='left').status_code == 404
    assert client.get('/version/1/download?project=2').status_code == 404
    assert client.get('/version/1/download?project=1').data == before


def test_jpeg_orientation_is_normalized_and_metadata_preserved(client, app):
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = 'Photographer'
    output = io.BytesIO()
    Image.new('RGB',(120,80),'red').save(output,'JPEG',exif=exif,dpi=(300,300),icc_profile=b'test-profile')
    upload(client, output.getvalue(), 'original.jpg')
    assert post(client, '/version/1/rotate', direction='right').status_code == 302
    with Image.open(io.BytesIO(client.get('/version/1/download').data)) as image:
        assert image.size == (120,80)
        assert image.getexif().get(274,1) == 1 and image.getexif()[315] == 'Photographer'
        assert image.info['icc_profile'] == b'test-profile'
        assert image.info['dpi'] == (300,300)


def test_animated_and_corrupt_files_are_untouched(client):
    output = io.BytesIO()
    Image.new('RGB',(10,20),'red').save(output,'GIF',save_all=True,append_images=[Image.new('RGB',(10,20),'blue')],duration=[100,200],loop=0)
    payload = upload(client,output.getvalue(),'animated.gif')
    assert post(client, '/version/1/rotate', direction='right').status_code == 409
    assert client.get('/version/1/download').data == payload
    upload(client,b'bad-image','bad.png')
    assert post(client, '/version/2/rotate', direction='left').status_code == 409
    assert client.get('/version/2/download').data == b'bad-image'


def test_workspace_selects_exact_linked_version(client):
    upload(client)
    output=io.BytesIO()
    Image.new('RGB',(40,60),'blue').save(output,'PNG')
    post(client,'/group/1',action='version',label='Edit',file=(io.BytesIO(output.getvalue()),'edited.png'))
    page = client.get('/group/1?version_id=1').data
    assert b'id="version-preview" src="/preview/1/display?project=1"' in page
    assert b'data-workspace-download href="/version/1/download?project=1"' in page
    assert client.get('/group/1?version_id=999').status_code == 404
    assert b'data-campaign-preview-workspace' in client.get('/campaign/1/new').data
