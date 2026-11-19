import hashlib
import io
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from app import db, PhotoGroup, PhotoVersion, UploadSession
from test_app import app, client, post

HEADERS = {'X-CSRF-Token':'token'}


def start(client, size, name='photo.png', project=1, group_id=None, token=None):
    payload={'id':token or uuid.uuid4().hex,'filename':name,'size':size,'label':'Original','group_id':group_id}
    return client.post(f'/uploads?project={project}',json=payload,headers=HEADERS)


def chunk(client, token, offset, body, project=1):
    return client.post(f'/uploads/{token}/chunks?project={project}',data=body,content_type='application/octet-stream',headers={**HEADERS,'Upload-Offset':str(offset)})


def finish(client, token, project=1):
    return client.post(f'/uploads/{token}/finish?project={project}',headers=HEADERS)


def part(app, token):
    return Path(app.config['MEDIA_ROOT'])/'.uploads'/(token+'.part')


def test_chunk_retries_offsets_and_idempotent_completion(client, app):
    token=uuid.uuid4().hex
    assert start(client,8,token=token).status_code==201
    assert start(client,8,token=token).get_json()['offset']==0
    assert start(client,9,token=token).status_code==409
    assert chunk(client,token,4,b'efgh').status_code==409
    assert chunk(client,token,0,b'abcd').get_json()['offset']==4
    assert chunk(client,token,0,b'abcd').get_json()['offset']==4
    assert chunk(client,token,0,b'xxxx').status_code==409
    assert finish(client,token).status_code==409
    # A write interrupted before its metadata commit cannot contaminate the next chunk.
    with part(app,token).open('ab') as target: target.write(b'crash-tail')
    assert chunk(client,token,4,b'efgh').get_json()['offset']==8
    assert finish(client,token).get_json()['status']=='complete'
    assert finish(client,token).get_json()['status']=='complete'
    assert not part(app,token).exists()
    with app.app_context():
        assert PhotoGroup.query.count()==PhotoVersion.query.count()==1
        version=PhotoVersion.query.one()
        assert Path(app.config['MEDIA_ROOT'],version.stored_path).read_bytes()==b'abcdefgh'
        assert version.content_hash==hashlib.sha256(b'abcdefgh').hexdigest()


def test_no_total_size_cap_and_bounded_requests(client, app):
    response=start(client,600*1024*1024)
    assert response.status_code==201
    token=response.get_json()['id']
    assert chunk(client,token,0,b'x'*(8*1024*1024+1)).status_code==413
    assert chunk(client,token,0,b'abc').status_code==200
    assert b'512 MB' not in client.get('/import').data
    assert app.config['MAX_CONTENT_LENGTH'] is None
    assert client.post(f'/uploads/{token}/cancel?project=1',headers=HEADERS).get_json()['status']=='cancelled'
    assert not part(app,token).exists()
    assert start(client,0).status_code==400
    assert start(client,10,name='script.exe').status_code==400


def test_ownership_project_scope_and_csrf(client, app, monkeypatch):
    token=start(client,4).get_json()['id']
    assert client.post('/uploads',json={}).status_code==400
    anonymous=app.test_client()
    denied=anonymous.get(f'/uploads/{token}')
    assert denied.status_code==401 and denied.is_json
    post(client,'/projects',action='create',name='Other project')
    assert client.get(f'/uploads/{token}?project=2').status_code==404
    assert chunk(client,token,0,b'data',project=2).status_code==404
    monkeypatch.setenv('OIDC_ALLOWED_SUBJECTS','')
    other=app.test_client()
    with other.session_transaction() as session: session.update(sub='other',csrf='token',profile_loaded=True)
    assert other.get(f'/uploads/{token}?project=1').status_code==404
    assert chunk(other,token,0,b'data').status_code==404
    assert chunk(client,token,0,b'data').status_code==200
    assert finish(client,token).status_code==200
    assert client.get('/uploads/../../app.db').status_code in (401,404)


def test_edited_versions_and_global_duplicate_detection(client, app):
    post(client,'/import',files=(io.BytesIO(b'original'),'original.png'))
    token=start(client,4,group_id=1).get_json()['id']
    assert chunk(client,token,0,b'edit').status_code==200
    assert finish(client,token).get_json()['redirect'].startswith('/group/1?project=1')
    duplicate=start(client,4).get_json()['id']
    chunk(client,duplicate,0,b'edit')
    assert finish(client,duplicate).get_json()['status']=='duplicate'
    assert finish(client,duplicate).get_json()['status']=='duplicate'
    assert not part(app,duplicate).exists()
    with app.app_context():
        assert PhotoGroup.query.count()==1 and PhotoVersion.query.count()==2
        assert all(version.content_hash for version in PhotoVersion.query.all())


def test_failed_finish_restores_staging_file_for_retry(client, app):
    token=start(client,4).get_json()['id']
    chunk(client,token,0,b'data')
    with app.app_context(): session_type=type(db.session())
    with patch.object(session_type,'commit',side_effect=RuntimeError('Commit failed')):
        with pytest.raises(RuntimeError,match='Commit failed'): finish(client,token)
    assert part(app,token).read_bytes()==b'data'
    with app.app_context():
        assert PhotoGroup.query.count()==PhotoVersion.query.count()==0
        assert db.session.get(UploadSession,token).status=='active'
    assert finish(client,token).get_json()['status']=='complete'


def test_cleanup_and_missing_partial_data(client, app):
    token=start(client,8).get_json()['id']
    chunk(client,token,0,b'part')
    part(app,token).unlink()
    assert chunk(client,token,4,b'data').status_code==409
    assert not part(app,token).exists()
    with app.app_context():
        db.session.get(UploadSession,token).updated_at=datetime.utcnow()-timedelta(days=2)
        db.session.commit()
    keep=Path(app.config['MEDIA_ROOT'])/'keep.png'; keep.write_bytes(b'keep')
    result=app.test_cli_runner().invoke(args=['uploads-cleanup'])
    assert result.exit_code==0,result.output
    with app.app_context(): assert db.session.get(UploadSession,token) is None
    assert keep.read_bytes()==b'keep'


def test_chunk_commit_failure_rolls_back_only_the_new_bytes(client, app):
    token=start(client,8).get_json()['id']
    chunk(client,token,0,b'abcd')
    with app.app_context(): session_type=type(db.session())
    with patch.object(session_type,'commit',side_effect=RuntimeError('Commit failed')):
        with pytest.raises(RuntimeError): chunk(client,token,4,b'efgh')
    assert part(app,token).read_bytes()==b'abcd'
    with app.app_context(): assert db.session.get(UploadSession,token).received_bytes==4
    assert chunk(client,token,4,b'efgh').get_json()['offset']==8
    assert finish(client,token).get_json()['status']=='complete'


def test_simultaneous_retries_do_not_append_the_same_chunk_twice(client, app):
    from concurrent.futures import ThreadPoolExecutor
    token=start(client,4).get_json()['id']
    def send(_):
        other=app.test_client()
        with other.session_transaction() as session:
            session.update(sub='allowed',csrf='token',profile_loaded=True)
        return chunk(other,token,0,b'data').get_json()['offset']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(send,range(2)))==[4,4]
    assert part(app,token).read_bytes()==b'data'
    assert finish(client,token).get_json()['status']=='complete'


def test_maximum_chunk_without_content_length(client, app):
    size=16*1024*1024
    token=start(client,size).get_json()['id']
    with app.app_context():
        db.session.get(UploadSession,token).chunk_bytes=size
        db.session.commit()
    response=client.post(f'/uploads/{token}/chunks?project=1',data=b'x'*size,
        content_type='application/octet-stream',headers={**HEADERS,'Upload-Offset':'0'},
        environ_overrides={'CONTENT_LENGTH':'','wsgi.input_terminated':True})
    assert response.status_code==200,response.get_json()
    assert response.get_json()['offset']==size
