import io
import uuid
from pathlib import Path

from PIL import Image, PngImagePlugin

from app import db, PhotoGroup, PhotoVersion, Tag, TagGroup
from image_analysis import inspect_image
from test_app import app, client, post


def png_bytes(colour=(255, 0, 0), size=(8, 4)):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('test-image', uuid.uuid4().hex)
    Image.new('RGB', size, colour).save(output, format='PNG', pnginfo=metadata)
    return output.getvalue()


def test_review_queue_decisions_tags_and_wraparound(client, app):
    for name in ('one.png', 'two.png', 'three.png'):
        post(client, '/import', files=(io.BytesIO(png_bytes()), name))
    post(client, '/tags', action='save_group', name='Type')
    post(client, '/tags', action='save_tag', name='Portrait', tag_group_id='1')
    for name in ('keeper', 'reviewed', 'candidate', 'rejected'):
        post(client, '/tags', action='save_tag', name=name)
    assert client.get('/pool/review').location.endswith('/pool/review/1')
    assert b'RGB histogram' in client.get('/pool/review/1').data
    assert b'Review Pool' in client.get('/gallery/pool').data
    result = post(client, '/pool/review/1', action='accept', tag=['1','2'])
    assert result.location.endswith('/pool/review/2')
    with app.app_context():
        photo = db.session.get(PhotoGroup, 1)
        assert photo.state == 'staging'
        assert {t.name for t in photo.tags} == {'Portrait', 'keeper'}
    # Previous/next wrap without changing workflow; each navigation saves tags.
    assert post(client, '/pool/review/2', action='previous', tag='3').location.endswith('/pool/review/3')
    assert post(client, '/pool/review/3', action='next').location.endswith('/pool/review/2')
    saved = post(client, '/pool/review/2', action='save', tag='4')
    assert '/pool/review/2' in saved.location
    with app.app_context():
        assert {t.name for t in db.session.get(PhotoGroup, 2).tags} == {'candidate'}
    result = post(client, '/pool/review/2', action='deny', tag='5')
    assert result.location.endswith('/pool/review/3')
    with app.app_context():
        assert db.session.get(PhotoGroup, 2).state == 'never_post'
    assert post(client, '/pool/review/2', action='accept', new_tags='stale').status_code == 409
    with app.app_context():
        assert db.session.get(PhotoGroup, 2).state == 'never_post'
        assert not Tag.query.filter_by(name='stale').first()
    assert post(client, '/pool/review/3', action='accept', version_id='1').status_code == 400
    assert client.post('/pool/review/3', data={'action': 'deny'}).status_code == 400
    assert post(client, '/pool/review/3', action='accept').location.endswith('/pool/review')
    assert b'Pool is empty' in client.get('/pool/review').data
    assert app.test_client().get('/pool/review').status_code == 302


def test_version_analysis_switch_and_invalid_file(client, app):
    post(client, '/import', files=(io.BytesIO(png_bytes()), 'original.png'))
    post(client, '/group/1', action='version', label='Blue edit', file=(io.BytesIO(png_bytes((0, 0, 255), (12, 6))), 'blue.png'))
    with app.app_context():
        original, edited = PhotoVersion.query.order_by(PhotoVersion.id).all()
        original_id, edited_id = original.id, edited.id
    post(client, '/tags', action='save_tag', name='kept')
    result = post(client, '/pool/review/1', action='preview', version_id=str(original_id), tag='1')
    assert f'version_id={original_id}' in result.location
    assert '8 × 4 px'.encode() in client.get(result.location).data
    page = client.get(f'/pool/review/1?version_id={edited_id}')
    assert b'Blue edit' in page.data
    with app.app_context():
        assert {t.name for t in db.session.get(PhotoGroup, 1).tags} == {'kept'}
        edited = db.session.get(PhotoVersion, edited_id)
        Path(app.config['MEDIA_ROOT'], edited.stored_path).write_bytes(b'corrupt')
    assert b'Image analysis unavailable.' in client.get(f'/pool/review/1?version_id={edited_id}').data
    assert post(client, '/pool/review/1', action='deny', version_id=str(edited_id)).status_code == 302


def test_metadata_and_real_histogram(tmp_path):
    path = tmp_path / 'test.png'
    info = PngImagePlugin.PngInfo()
    info.add_text('Description', 'Metadata test')
    exif = Image.Exif(); exif[271] = 'Test camera'; exif[274] = 1
    Image.new('RGB', (8, 4), (255, 0, 0)).save(path, pnginfo=info, exif=exif)
    before = path.read_bytes()
    result = inspect_image(tmp_path, 'test.png')
    assert result['error'] is None
    sections = {name: dict(rows) for name, rows in result['sections']}
    assert sections['Image']['Dimensions'] == '8 × 4 px'
    assert sections['EXIF']['Make'] == 'Test camera'
    assert sections['Embedded metadata']['Description'] == 'Metadata test'
    red, green, blue = result['histogram']['bins']
    assert red[255] == 32 and green[0] == blue[0] == 32
    assert all(sum(channel) == 32 for channel in (red, green, blue))
    assert len(result['histogram']['paths']) == 3
    assert path.read_bytes() == before
    assert inspect_image(tmp_path, 'missing.png')['histogram'] is None
    assert inspect_image(tmp_path, '../outside.png')['error']


def test_histogram_is_bounded(tmp_path):
    Image.new('RGB', (2400, 1200), (12, 40, 80)).save(tmp_path / 'large.png')
    result = inspect_image(tmp_path, 'large.png')
    assert result['histogram']['sample_size'] == (1024, 512)
    assert sum(result['histogram']['bins'][0]) == 1024 * 512
