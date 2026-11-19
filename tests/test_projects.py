import io
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import db, Project, PhotoGroup, PhotoVersion, Campaign, CampaignDestination
from test_app import app, client, post


def create_project(client, name='Client work'):
    response = post(client, '/projects', action='create', name=name)
    assert response.status_code == 302
    return int(parse_qs(urlparse(response.location).query)['project'][0])


def upload(client, project, name, content):
    return post(client, f'/import?project={project}', files=(io.BytesIO(content), name))


def test_project_management_and_switching(client, app):
    assert b'Main library' in client.get('/').data
    assert client.post('/projects', data={'action':'create','name':'No CSRF'}).status_code == 400
    assert post(client, '/projects', action='create', name=' ').status_code == 400
    second = create_project(client)
    assert second == 2
    assert post(client, '/projects', action='create', name='client WORK').status_code == 409
    assert post(client, '/projects', action='rename', project_id=str(second), name='Personal').status_code == 302
    assert b'Personal' in client.get('/projects').data
    response = post(client, '/projects/switch', project_id='1', return_state='staging')
    assert response.location == '/gallery/staging?project=1'
    assert post(client, '/projects/switch', project_id='9999').status_code == 404
    assert client.get('/?project=nope').status_code == 400
    assert client.get('/?project=9999').status_code == 404
    assert post(client, '/projects', action='delete', project_id=str(second)).status_code == 302
    assert post(client, '/projects', action='delete', project_id='1').status_code == 409
    with app.app_context():
        assert Project.query.count() == 1


def test_photos_review_media_and_campaigns_are_scoped(client, app):
    upload(client, 1, 'main-only.png', b'main')
    post(client, '/accounts', action='platform', name='Network')
    post(client, '/accounts', action='account', platform_id='1', display_name='Reusable account', handle='@account', active='on')
    post(client, '/tags', action='save_tag', name='Reusable tag')
    post(client, '/campaign/1/new?project=1', name='Main campaign', version_id='1', accounts='1')
    second = create_project(client)
    upload(client, second, 'client-only.png', b'client')
    main = client.get('/gallery/all?project=1')
    other = client.get(f'/gallery/all?project={second}')
    assert b'main-only.png' in main.data and b'client-only.png' not in main.data
    assert b'client-only.png' in other.data and b'main-only.png' not in other.data
    assert b'Pool: 1 photo groups' in client.get(f'/?project={second}').data
    assert client.get(f'/pool/review?project={second}').location == f'/pool/review/2?project={second}'
    assert b'Reusable tag' in client.get(f'/group/2?project={second}').data
    assert b'Reusable account' in client.get(f'/campaign/2/new?project={second}').data
    with app.app_context():
        path = PhotoVersion.query.filter_by(group_id=1).one().stored_path
    for route in ['/group/1', '/pool/review/1', '/group/1/delete', '/group/1/version/1/delete', '/campaign/1/new', '/campaign/edit/1', '/media/'+path]:
        assert client.get(route+f'?project={second}').status_code == 404, route
    assert post(client, f'/group/1?project={second}', action='state', state='staging').status_code == 404
    assert post(client, f'/group/1/delete?project={second}', confirm='delete').status_code == 404
    assert post(client, f'/library/bulk?project={second}', action='edit', photo_ids='1').status_code == 409
    assert post(client, '/projects', action='delete', project_id='1').status_code == 409
    with app.app_context():
        assert db.session.get(PhotoGroup, 1).state == 'pool'
        assert Campaign.query.count() == CampaignDestination.query.count() == 1


def test_tabs_and_filter_forms_keep_their_project(client, app):
    second = create_project(client)
    old_page = client.get('/import?project=1')
    assert b'name="project_context" value="1"' in old_page.data
    assert b'/gallery/all?project=1' in old_page.data
    filters = client.get('/gallery/all?project=1')
    assert b'name="project" value="1"' in filters.data
    assert b'No matching photos' not in filters.data
    # Visiting an older tab must not overwrite the sidebar switcher's saved selection.
    with client.session_transaction() as session:
        assert session['project_id'] == second
    post(client, '/import', project_context='1', files=(io.BytesIO(b'old-tab'), 'old-tab.png'))
    assert post(client, f'/import?project={second}', project_context='1', files=(io.BytesIO(b'conflict'), 'conflict.png')).status_code == 400
    upload(client, second, 'new-tab.png', b'new-tab')
    with app.app_context():
        assert [(photo.project_id, photo.versions[0].original_filename) for photo in PhotoGroup.query.order_by(PhotoGroup.id)] == [(1,'old-tab.png'), (second,'new-tab.png')]


def test_bulk_move_preserves_campaigns_versions_and_duplicate_prevention(client, app):
    upload(client, 1, 'move-me.png', b'move-me')
    post(client, '/accounts', action='platform', name='Network')
    post(client, '/accounts', action='account', platform_id='1', display_name='Account', handle='@account', active='on')
    post(client, '/campaign/1/new?project=1', name='Campaign', version_id='1', accounts='1')
    second = create_project(client)
    with app.app_context():
        stored = PhotoVersion.query.one().stored_path
    result = post(client, '/library/bulk?project=1', action='apply', photo_ids='1', state_before_1='pool', target_project_id=str(second), tag_mode='keep')
    assert result.status_code == 302
    assert b'move-me.png' not in client.get('/gallery/all?project=1').data
    assert b'move-me.png' in client.get(f'/gallery/all?project={second}&status=planned').data
    with app.app_context():
        assert db.session.get(PhotoGroup, 1).project_id == second
        assert Campaign.query.one().group_id == 1
        assert CampaignDestination.query.count() == 1
        assert PhotoVersion.query.one().stored_path == stored
        assert Path(app.config['MEDIA_ROOT'],stored).read_bytes() == b'move-me'
    upload(client, 1, 'renamed.png', b'move-me')
    with app.app_context():
        assert PhotoGroup.query.count() == PhotoVersion.query.count() == 1
    with client.session_transaction() as session:
        assert any('Client work' in message and 'Duplicate skipped' in message for _,message in session['_flashes'])


def test_original_project_can_be_deleted_without_redirecting_new_imports(client, app):
    second = create_project(client)
    assert post(client, '/projects', action='delete', project_id='1').status_code == 302
    assert post(client, '/import', files=(io.BytesIO(b'new-default'), 'photo.png')).status_code == 302
    with app.app_context():
        assert Project.query.one().id == second
        assert PhotoGroup.query.one().project_id == second


def test_deleted_project_ids_are_not_reused_by_new_projects(client):
    old = create_project(client, 'Temporary')
    assert post(client, '/projects', action='delete', project_id=str(old)).status_code == 302
    new = create_project(client, 'New collection')
    assert new > old
    assert client.get(f'/import?project={old}').status_code == 404
