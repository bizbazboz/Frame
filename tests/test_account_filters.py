import io
import re
from urllib.parse import urlparse, parse_qs

from app import db, PhotoGroup
from test_app import app, client, post
from test_review import png_bytes


def avatar_url(response):
    match=re.search(r'<img src="(https://api\.dicebear\.com/[^"]+)"', response.get_data(as_text=True))
    assert match
    return match.group(1)


def test_sidebar_account_and_opaque_identicon(client, app):
    with client.session_transaction() as session:
        session['display_name']='Studio User'
    response=client.get('/')
    assert b'class="topbar"' not in response.data
    assert b'Signed-in account' in response.data and b'Studio User' in response.data
    assert b'sidebar-logout' in response.data
    url=avatar_url(response)
    assert urlparse(url).path == '/10.x/notionists/svg'
    seed=parse_qs(urlparse(url).query)['seed'][0]
    assert len(seed)==64 and 'allowed' not in url
    assert avatar_url(client.get('/'))==url
    assert b'referrerpolicy="no-referrer"' in response.data
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/logout', data={'csrf_token':csrf}).status_code==302
    assert client.get('/').status_code==302


def test_callback_captures_display_name_and_fallback(app):
    class OIDC:
        def authorize_access_token(self):
            return {'userinfo':{'sub':'allowed','name':'  Photo User  ','preferred_username':'handle'}}
    app.extensions['oidc_client']=OIDC()
    client=app.test_client()
    assert client.get('/auth/callback').status_code==302
    with client.session_transaction() as session:
        assert session['display_name']=='Photo User'
    class Fallback:
        def authorize_access_token(self):
            return {'userinfo':{'sub':'allowed','preferred_username':'photo-user'}}
    app.extensions['oidc_client']=Fallback()
    assert client.get('/auth/callback').status_code==302
    with client.session_transaction() as session:
        assert session['display_name']=='photo-user'


def test_gallery_tag_group_filters_combine_with_tags_and_state(client, app):
    for name in ('one.png','two.png','three.png'):
        post(client,'/import',files=(io.BytesIO(png_bytes()),name))
    post(client,'/tags',action='save_group',name='Type')
    post(client,'/tags',action='save_group',name='Safety')
    post(client,'/tags',action='save_tag',name='Portrait',tag_group_id='1')
    post(client,'/tags',action='save_tag',name='Safe',tag_group_id='2')
    post(client,'/tags',action='save_tag',name='Legacy')
    post(client,'/group/1',action='tags',tag=['1','2'])
    post(client,'/group/2',action='tags',tag=['1'])
    post(client,'/group/3',action='tags',tag=['3'])
    post(client,'/group/2',action='state',state='staging')
    response=client.get('/gallery/all?tag_group=2&tag=1')
    assert response.status_code==200
    assert b'one.png' in response.data and b'two.png' not in response.data and b'three.png' not in response.data
    assert b'value="2" selected>Safety' in response.data
    response=client.get('/gallery/staging?tag_group=1')
    assert b'two.png' in response.data and b'one.png' not in response.data
    response=client.get('/gallery/all?tag_group=ungrouped')
    assert b'three.png' in response.data and b'one.png' not in response.data
    assert client.get('/gallery/all?tag_group=invalid').status_code==400
    post(client,'/tags',action='delete_group',id='2')
    response=client.get('/gallery/all?tag_group=ungrouped')
    assert b'one.png' in response.data and b'three.png' in response.data

def test_oidc_display_name_claim_and_legacy_session_refresh(app):
    class OIDC:
        def authorize_access_token(self):
            return {'userinfo':{'sub':'allowed','display_name':'My OIDC Name','name':'Different full name','preferred_username':'handle'}}
    app.extensions['oidc_client']=OIDC()
    client=app.test_client()
    with client.session_transaction() as session:
        session['sub']='allowed'; session['csrf']='old'; session['display_name']='User'
    result=client.get('/gallery/staging?tag_group=1')
    assert result.status_code==302 and result.location.endswith('/login')
    result=client.get('/auth/callback')
    assert result.location.endswith('/gallery/staging?tag_group=1')
    with client.session_transaction() as session:
        assert session['display_name']=='My OIDC Name' and session['profile_loaded'] is True
    response=client.get('/')
    assert response.status_code==200 and b'My OIDC Name' in response.data
    assert b'aria-label="Log out"' in response.data


def test_missing_profile_claims_do_not_cause_refresh_loop(app):
    class OIDC:
        def authorize_access_token(self): return {'userinfo':{'sub':'allowed'}}
    app.extensions['oidc_client']=OIDC()
    client=app.test_client()
    assert client.get('/auth/callback').status_code==302
    assert client.get('/').status_code==200
