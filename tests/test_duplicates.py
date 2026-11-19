import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import db, PhotoGroup, PhotoVersion
from test_app import app, client, post


def upload(client, content, name='photo.png'):
    return post(client, '/import', files=(io.BytesIO(content), name))


def assert_library(app, count):
    with app.app_context():
        assert PhotoGroup.query.count() == count
        assert PhotoVersion.query.count() == count
        root = Path(app.config['MEDIA_ROOT'])
        paths = {root / version.stored_path for version in PhotoVersion.query.all()}
        assert {path for path in root.rglob('*') if path.is_file() and path.name != '.library-write.lock'} == paths


def test_duplicates_in_batch_and_renamed_reuploads(client, app):
    result = post(client, '/import', files=[
        (io.BytesIO(b'original'), 'one.png'),
        (io.BytesIO(b'original'), 'renamed.jpg'),
        (io.BytesIO(b'different'), 'one.png'),
    ])
    assert result.status_code == 302
    assert_library(app, 2)
    assert upload(client, b'original', 'another.webp').status_code == 302
    assert_library(app, 2)
    with client.session_transaction() as session:
        assert any('Duplicate skipped' in message for _, message in session['_flashes'])


def test_duplicates_across_groups_versions_and_existing_database(client, app):
    # Simulate an existing library without a hash column or sidecar index.
    with app.app_context():
        group = PhotoGroup(state='never_post')
        db.session.add(group)
        db.session.flush()
        root = Path(app.config['MEDIA_ROOT'])
        (root / str(group.id)).mkdir()
        (root / str(group.id) / 'legacy.png').write_bytes(b'legacy')
        db.session.add(PhotoVersion(group=group, label='Original', original_filename='legacy.png', stored_path=f'{group.id}/legacy.png'))
        db.session.commit()
    upload(client, b'legacy', 'renamed.png')
    assert_library(app, 1)
    upload(client, b'new-original')
    post(client, '/group/2', action='version', file=(io.BytesIO(b'legacy'), 'edit.png'))
    assert_library(app, 2)
    post(client, '/group/2', action='version', file=(io.BytesIO(b'new-edit'), 'edit.png'))
    post(client, '/group/1', action='version', file=(io.BytesIO(b'new-edit'), 'another.png'))
    upload(client, b'new-edit')
    with app.app_context():
        assert PhotoGroup.query.count() == 2
        assert PhotoVersion.query.count() == 3


def test_simultaneous_duplicate_uploads(app):
    def send(name):
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(sub='allowed', csrf='token', profile_loaded=True)
        return upload(client, b'simultaneous', name).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(send, ['first.png', 'second.jpg'])) == [302, 302]
    assert_library(app, 1)


def test_failed_commit_removes_new_media(client, app, monkeypatch):
    with app.app_context():
        session_type = type(db.session())
    def fail(*args, **kwargs):
        raise RuntimeError('Commit failed')
    monkeypatch.setattr(session_type, 'commit', fail)
    with pytest.raises(RuntimeError, match='Commit failed'):
        upload(client, b'failed-upload')
    assert_library(app, 0)
    monkeypatch.undo()
    upload(client, b'failed-upload')
    assert_library(app, 1)
