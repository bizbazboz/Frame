import io
from pathlib import Path
from unittest.mock import patch

from app import db, PhotoGroup, PhotoVersion, Tag, Platform, SocialAccount, Campaign, CampaignDestination, group_tags
from media_deletion import delete_with_media, MediaDeletionError
from test_app import app, client, post
from test_review import png_bytes


def import_photo(client, filename='original.png'):
    return post(client, '/import', files=(io.BytesIO(png_bytes()), filename))


def test_photo_screens_are_selection_only(client, app):
    import_photo(client)
    post(client, '/tags', action='save_group', name='Image type')
    post(client, '/tags', action='save_tag', name='Portrait', tag_group_id='1')
    post(client, '/tags', action='save_tag', name='Other')
    for url in ('/group/1', '/pool/review/1'):
        page = client.get(url)
        assert b'name="new_tags"' not in page.data
        assert b'Image type' in page.data and b'Uncategorised' in page.data
        action = 'tags' if url.startswith('/group') else 'save'
        assert post(client, url, action=action, new_tags='forged').status_code == 400
        assert post(client, url, action=action, tag='999').status_code == 400
        assert post(client, url, action=action, tag='1').status_code == 302
    with app.app_context():
        assert Tag.query.count() == 2
        assert [t.name for t in db.session.get(PhotoGroup, 1).tags] == ['Portrait']
    review = client.get('/pool/review/1').data
    assert review.index(b'<h2>RGB histogram</h2>') < review.index(b'<h2>Tags</h2>')


def test_version_delete_and_protections(client, app):
    import_photo(client)
    assert client.get('/group/1/version/1/delete').status_code == 409
    post(client, '/group/1', action='version', label='Edit', file=(io.BytesIO(png_bytes()), 'edit.png'))
    import_photo(client, 'other.png')
    with app.app_context():
        original = db.session.get(PhotoVersion, 1)
        edited = db.session.get(PhotoVersion, 2)
        original_path = Path(app.config['MEDIA_ROOT'], original.stored_path)
        edit_path = Path(app.config['MEDIA_ROOT'], edited.stored_path)
    assert client.get('/group/1/version/2/delete').status_code == 200
    assert edit_path.exists()
    assert client.post('/group/1/version/2/delete', data={'confirm':'delete'}).status_code == 400
    assert post(client, '/group/1/version/2/delete').status_code == 400
    assert client.get('/group/2/version/2/delete').status_code == 404
    result = post(client, '/group/1/version/2/delete', confirm='delete')
    assert result.location.endswith('/group/1')
    assert not edit_path.exists() and original_path.exists()
    with app.app_context():
        assert db.session.get(PhotoVersion, 2) is None
        assert len(db.session.get(PhotoGroup, 1).versions) == 1
    assert app.test_client().post('/group/1/delete').status_code == 302


def test_group_deletes_campaigns_files_but_preserves_shared_tags(client, app):
    import_photo(client)
    import_photo(client, 'keep.png')
    with app.app_context():
        photo = db.session.get(PhotoGroup, 1)
        tag = Tag(name='Shared')
        photo.tags.append(tag)
        other = db.session.get(PhotoGroup, 2)
        other.tags.append(tag)
        platform = Platform(name='Network')
        account = SocialAccount(platform=platform, display_name='Account', handle='@test')
        campaign = Campaign(group=photo, version=photo.versions[0], name='Campaign')
        db.session.add_all([platform,account,campaign])
        db.session.add(CampaignDestination(campaign=campaign,account=account,status='published'))
        db.session.commit()
        image_path = Path(app.config['MEDIA_ROOT'], photo.versions[0].stored_path)
        untracked = image_path.parent / 'untracked.png'; untracked.write_bytes(b'preserve')
        keep_path = Path(app.config['MEDIA_ROOT'], db.session.get(PhotoGroup, 2).versions[0].stored_path)
    assert client.get('/group/1/delete').status_code == 200
    assert image_path.exists()
    assert post(client, '/group/1/delete').status_code == 400
    result = post(client, '/group/1/delete', confirm='delete')
    assert result.location.endswith('/gallery/pool')
    assert not image_path.exists() and keep_path.exists() and untracked.exists()
    with app.app_context():
        assert db.session.get(PhotoGroup, 1) is None
        assert Campaign.query.count() == CampaignDestination.query.count() == 0
        assert SocialAccount.query.count() == Tag.query.count() == 1
        assert db.session.query(group_tags).count() == 1


def test_campaign_version_cannot_be_deleted(client, app):
    import_photo(client)
    post(client, '/group/1', action='version', label='Edit', file=(io.BytesIO(png_bytes()), 'edit.png'))
    with app.app_context():
        photo = db.session.get(PhotoGroup, 1)
        db.session.add(Campaign(group=photo, version=photo.versions[1], name='Keep history'))
        db.session.commit()
    assert post(client, '/group/1/version/2/delete', confirm='delete').status_code == 409
    with app.app_context():
        assert db.session.get(PhotoVersion, 2) is not None


def test_review_delete_confirmation_then_advance(client, app):
    import_photo(client)
    import_photo(client, 'next.png')
    result = post(client, '/pool/review/1', action='confirm_delete_group')
    assert '/group/1/delete?origin=review' in result.location
    assert client.get(result.location).status_code == 200
    with app.app_context():
        assert PhotoGroup.query.count() == 2
    result = post(client, '/group/1/delete', confirm='delete', origin='review')
    assert result.location.endswith('/pool/review/2')
    result = post(client, '/group/2/delete', confirm='delete', origin='review')
    assert result.location.endswith('/pool/review')
    assert b'Pool is empty' in client.get(result.location).data


def test_deletion_failure_restores_staged_images(client, app):
    import_photo(client)
    with app.app_context():
        photo = db.session.get(PhotoGroup, 1)
        path = Path(app.config['MEDIA_ROOT'], photo.versions[0].stored_path)
        before = path.read_bytes()
        with patch.object(db.session, 'commit', side_effect=RuntimeError('commit failed')):
            try:
                delete_with_media(db, photo, list(photo.versions), app.config['MEDIA_ROOT'])
            except MediaDeletionError:
                pass
            else:
                raise AssertionError('Expected failed deletion')
        assert path.read_bytes() == before
        assert db.session.get(PhotoGroup, 1) is not None
        assert list(Path(app.config['MEDIA_ROOT']).glob('.deleting-*')) == []

def test_delete_refuses_paths_outside_managed_group(client, app, tmp_path):
    import_photo(client)
    outside = tmp_path / 'outside.png'; outside.write_bytes(b'keep')
    with app.app_context():
        version = db.session.get(PhotoVersion, 1)
        version.stored_path = str(outside)
        db.session.commit()
    assert post(client, '/group/1/delete', confirm='delete').status_code == 409
    assert outside.read_bytes() == b'keep'
    with app.app_context():
        assert db.session.get(PhotoGroup, 1) is not None
