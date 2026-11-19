import io
from pathlib import Path
from unittest.mock import patch

from app import db, PhotoGroup, PhotoVersion, Tag, Campaign, CampaignDestination, Platform, SocialAccount
from test_app import app, client, post
from test_review import png_bytes


def seed(client):
    for name in ('one.png','two.png','three.png'):
        post(client, '/import', files=(io.BytesIO(png_bytes()), name))
    post(client, '/tags', action='save_group', name='Type')
    post(client, '/tags', action='save_tag', name='Portrait', tag_group_id='1')
    post(client, '/tags', action='save_tag', name='Landscape', tag_group_id='1')
    post(client, '/group/1', action='tags', tag='1')


def apply(client, action='apply', **data):
    return post(client, '/library/bulk', photo_ids=['1','2'], return_state='all',
                state_before_1='pool', state_before_2='pool', action=action, **data)


def test_bulk_selection_and_tag_modes(client, app):
    seed(client)
    for state in ('pool','staging','never_post','final','all'):
        page = client.get('/gallery/'+state)
        assert page.status_code == 200
    page = client.get('/gallery/pool')
    assert page.data.count(b'data-photo-select') == 3
    editor = post(client, '/library/bulk', action='edit', photo_ids=['1','2'], return_state='pool')
    assert editor.status_code == 200 and b'one.png' in editor.data and b'two.png' in editor.data
    assert b'three.png' not in editor.data
    assert b'name="new_tags"' not in editor.data
    result = apply(client, state='staging', tag_mode='add', tag='2')
    assert result.status_code == 302
    with app.app_context():
        one = db.session.get(PhotoGroup, 1); two = db.session.get(PhotoGroup, 2)
        assert one.state == two.state == 'staging'
        assert {t.id for t in one.tags} == {1,2}
        assert {t.id for t in two.tags} == {2}
        assert db.session.get(PhotoGroup, 3).state == 'pool'
    for mode, values, expected in [('remove',['1'],{2}),('replace',[],set()),('add',['1'],{1}),('keep',['2'],{1})]:
        result = post(client, '/library/bulk', action='apply', photo_ids=['1','2'], return_state='staging',
                      state_before_1='staging', state_before_2='staging', tag_mode=mode, tag=values)
        assert result.status_code == 302
        with app.app_context():
            assert {t.id for t in db.session.get(PhotoGroup,1).tags} == expected
            assert {t.id for t in db.session.get(PhotoGroup,2).tags} == expected


def test_bulk_validation_and_stale_selection_are_atomic(client, app):
    seed(client)
    assert post(client, '/library/bulk', action='edit').status_code == 400
    assert post(client, '/library/bulk', action='edit', photo_ids=['no']).status_code == 400
    assert post(client, '/library/bulk', action='edit', photo_ids=['1','999']).status_code == 409
    assert apply(client, state='final').status_code == 400
    assert apply(client, tag_mode='add', tag='999').status_code == 400
    assert apply(client, new_tags='forged').status_code == 400
    assert apply(client, tag_mode='invalid').status_code == 400
    assert client.post('/library/bulk', data={'action':'edit','photo_ids':'1'}).status_code == 400
    with app.app_context():
        second = db.session.get(PhotoGroup,2); second.state='staging'; db.session.commit()
    assert apply(client, state='never_post', tag_mode='replace').status_code == 409
    with app.app_context():
        assert db.session.get(PhotoGroup,1).state == 'pool'
        assert [t.id for t in db.session.get(PhotoGroup,1).tags] == [1]
        assert db.session.get(PhotoGroup,2).state == 'staging'
        assert Tag.query.count() == 2
    assert app.test_client().post('/library/bulk').status_code == 302


def test_bulk_delete_confirmation_campaigns_and_files(client, app):
    seed(client)
    with app.app_context():
        photos = PhotoGroup.query.order_by(PhotoGroup.id).all()
        paths = [Path(app.config['MEDIA_ROOT'], photo.versions[0].stored_path) for photo in photos]
        platform = Platform(name='Network')
        account = SocialAccount(platform=platform,display_name='Account',handle='@test')
        campaign = Campaign(group=photos[0],version=photos[0].versions[0],name='Campaign')
        db.session.add_all([account,campaign]); db.session.add(CampaignDestination(campaign=campaign,account=account))
        db.session.commit()
    confirmation = post(client, '/library/bulk', action='delete', photo_ids=['1','2'], return_state='all')
    assert confirmation.status_code == 200 and b'Delete selected photo groups?' in confirmation.data
    assert all(path.exists() for path in paths)
    assert apply(client, action='confirm_delete').status_code == 400
    assert apply(client, action='confirm_delete', confirm='delete').status_code == 302
    assert not paths[0].exists() and not paths[1].exists() and paths[2].exists()
    with app.app_context():
        assert [photo.id for photo in PhotoGroup.query.all()] == [3]
        assert Campaign.query.count() == CampaignDestination.query.count() == 0
        assert Tag.query.count() == 2 and SocialAccount.query.count() == 1


def test_bulk_delete_commit_failure_restores_every_file(client, app):
    seed(client)
    with app.app_context():
        paths=[Path(app.config['MEDIA_ROOT'],v.stored_path) for v in PhotoVersion.query.order_by(PhotoVersion.id).all()]
        before=[path.read_bytes() for path in paths]
    with patch.object(db.session, 'commit', side_effect=RuntimeError('commit failed')):
        result=apply(client, action='confirm_delete', confirm='delete')
    assert result.status_code == 409
    assert [path.read_bytes() for path in paths] == before
    with app.app_context():
        assert PhotoGroup.query.count() == 3
    assert list(Path(app.config['MEDIA_ROOT']).glob('.deleting-*')) == []
