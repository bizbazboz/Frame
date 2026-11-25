import io
from pathlib import Path

from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import db, Campaign, CampaignImage, CampaignDestination, PhotoGroup, PhotoVersion, Project
from test_app import app, client, post
from test_review import png_bytes


def seed(client):
    for name in ('one.png', 'two.png', 'three.png'):
        post(client, '/import', files=(io.BytesIO(png_bytes()), name))
    post(client, '/accounts', action='platform', name='Reddit')
    for name in ('artist_one', 'artist_two'):
        post(client, '/accounts', action='account', platform_id='1', display_name=name, handle=name, active='on')


def save(client, path='/campaigns/new', **changes):
    data = dict(name='Summer carousel', version_ids=['1','2'], accounts=['1','2'], status_1='published',
                date_1='2026-11-20T10:00', url_1='https://reddit.com/comments/abc', status_2='planned')
    data.update(changes)
    return post(client, path, **data)


def test_ordered_images_publication_and_all_group_links(client, app):
    seed(client)
    assert client.get('/campaigns/new').status_code == 200
    assert save(client).status_code == 302
    with app.app_context():
        campaign = Campaign.query.one()
        assert [v.id for v in campaign.versions] == [1,2]
        assert [db.session.get(PhotoGroup, id).state for id in (1,2)] == ['final','final']
        assert len(db.session.get(PhotoGroup,2).linked_campaigns) == 1
    assert b'Summer carousel' in client.get('/group/2').data
    gallery = client.get('/gallery/all?account=1&status=published').data
    assert b'one.png' in gallery and b'two.png' in gallery and b'three.png' not in gallery
    assert save(client, '/campaign/edit/1', version_ids=['2','1']).status_code == 302
    with app.app_context():
        campaign = Campaign.query.one()
        assert [v.id for v in campaign.versions] == [2,1]
        assert campaign.group_id == 2 and campaign.version_id == 2
    assert save(client, '/campaign/edit/1', version_ids=['2'], accounts=['1']).status_code == 302
    with app.app_context():
        assert CampaignImage.query.count() == CampaignDestination.query.count() == 1
        assert not db.session.get(PhotoGroup,1).linked_campaigns
    assert save(client, '/campaign/edit/1', version_ids=['2','3'], accounts=['1'], date_1='').status_code == 302
    with app.app_context():
        assert db.session.get(PhotoGroup,3).state == 'final'
        assert CampaignDestination.query.one().published_at.isoformat() == '2026-11-20T10:00:00'


def test_campaign_filters_match_same_destination(client):
    seed(client)
    save(client)
    assert b'Summer carousel' in client.get('/campaigns?account=1&status=published&start=2026-11-20&end=2026-11-20&q=Summer').data
    assert b'Summer carousel' not in client.get('/campaigns?account=2&status=published').data
    assert b'Summer carousel' in client.get('/campaigns?account=2&status=planned').data
    assert b'Summer carousel' not in client.get('/campaigns?status=unassigned').data
    assert client.get('/campaigns?start=bad').status_code == 400


def test_campaign_scope_never_post_and_validation(client, app):
    seed(client)
    for ids in ([], ['1','1'], ['999']):
        assert save(client, version_ids=ids).status_code == 400
    post(client, '/group/2', action='state', state='never_post')
    assert save(client).status_code == 403
    with app.app_context():
        db.session.add(Project(name='Other'))
        db.session.commit()
    post(client, '/import?project=2', files=(io.BytesIO(png_bytes()), 'other.png'))
    assert save(client, version_ids=['1','4']).status_code == 400
    assert save(client, version_ids=['1']).status_code == 302
    assert client.get('/campaign/edit/1?project=2').status_code == 404
    assert client.get('/campaign/1/delete?project=2').status_code == 404
    assert b'Summer carousel' not in client.get('/campaigns?project=2').data
    assert app.test_client().get('/campaigns').status_code == 302
    assert client.post('/campaigns/new', data={'name':'forged','version_ids':['1']}).status_code == 400


def test_deletion_and_move_protect_every_image(client, app):
    seed(client)
    save(client)
    post(client, '/group/2', action='version', label='Edit', file=(io.BytesIO(png_bytes()),'edit.png'))
    assert client.get('/group/2/version/2/delete').status_code == 409
    assert client.get('/group/1/delete').status_code == 409
    with app.app_context():
        db.session.add(Project(name='Other'))
        db.session.commit()
    assert post(client, '/library/bulk', action='apply', photo_ids=['1'], state_before_1='final', target_project_id='2').status_code == 409
    response = post(client, '/library/bulk', action='apply', photo_ids=['1','2'], state_before_1='final', state_before_2='final', target_project_id='2')
    assert response.status_code == 302
    assert b'Summer carousel' in client.get('/campaigns?project=2').data
    assert client.get('/campaigns?project=1').status_code == 200
    assert post(client, '/library/bulk?project=2', action='confirm_delete', confirm='delete', photo_ids=['1','2'], state_before_1='final', state_before_2='final').status_code == 302
    with app.app_context():
        assert Campaign.query.count() == CampaignImage.query.count() == 0
        assert PhotoGroup.query.count() == 1


def test_campaign_delete_preserves_library(client, app):
    seed(client)
    save(client)
    assert client.get('/campaign/1/delete').status_code == 200
    assert post(client, '/campaign/1/delete').status_code == 400
    assert post(client, '/campaign/1/delete', confirm='delete').status_code == 302
    with app.app_context():
        assert Campaign.query.count() == CampaignImage.query.count() == CampaignDestination.query.count() == 0
        assert PhotoGroup.query.count() == PhotoVersion.query.count() == 3
        assert all((Path(app.config['MEDIA_ROOT']) / v.stored_path).exists() for v in PhotoVersion.query.all())


def test_migration_backfills_old_campaign_selected_version(client, app):
    seed(client)
    with app.app_context():
        downgrade(revision='0005')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO campaign (id, group_id, version_id, name) VALUES (1,1,1,'Existing campaign')"))
        upgrade()
        assert CampaignImage.query.one().version_id == 1
        assert Campaign.query.one().name == 'Existing campaign'
