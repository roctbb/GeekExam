from datetime import timedelta
import uuid

from conftest import observation
from test_service import CSRF, service_header, sync, device_id
from guard_service.models import db, BrowserProof, NetworkSession

CLIENT = str(uuid.uuid4())
ORIGIN = 'https://exam.geekclass.ru'
ENDPOINT = 'https://lan-409.guard.geekclass.ru:18766'


def exam(app, path, **values):
    return app.test_client().post('/api/v1/internal/exams/network/proofs/'+path,
        headers=service_header(app,'EXAM_SERVICE_SECRET','guard:exams','geekexam'),
        json={'actor_id':2,'room_id':'room-a','user_id':4,'attempt_id':10,'client_id':CLIENT,**values})


def setup(app, login, enroll):
    headers,_ = enroll('router-a')
    sync(app,headers)
    response = login(1).put('/api/v1/routers/router-a/browser-proof',headers=CSRF,
        json={'version':0,'origin':ENDPOINT,'enabled':True})
    assert response.status_code == 200,response.json
    started = exam(app,'start')
    assert started.status_code == 200,started.json
    return headers,started.json['items'][0]


def complete(app, headers, item, **values):
    return app.test_client().post('/api/v1/agent/proofs/complete',headers=headers,json={
        'token':item['token'],'origin':ORIGIN,'endpoint_origin':ENDPOINT,
        'peer_ip':'192.0.2.139','mac':'02:00:00:00:00:01','epoch':'connection-1',
        'boot_id':'boot-one','source_age_seconds':0,**values})


def test_first_device_proof_creates_network_session_and_is_bound_to_attempt_client(app,login,enroll):
    headers,item=setup(app,login,enroll)
    assert item['url']==ENDPOINT+'/v1/browser-proof'
    assert set(item)=={'id','token','url'}
    assert complete(app,headers,item).json['state']=='proved'
    result=exam(app,'consume',proof_id=item['id'])
    assert result.status_code==200,result.json
    assert result.json['user_id']==4 and result.json['method']=='browser_lan_proof'
    assert result.json['device_id']==device_id(app)
    assert exam(app,'consume',proof_id=item['id']).json['session_id']==result.json['session_id']
    assert exam(app,'consume',proof_id=item['id'],attempt_id=11).status_code==403
    assert exam(app,'consume',proof_id=item['id'],client_id='another-client').status_code==403
    assert complete(app,headers,item).status_code==409
    with app.app_context():
        assert db.session.get(BrowserProof,item['id']).consumed_at is not None
        assert db.session.query(NetworkSession).count()==1


def test_proof_requires_agent_identity_current_epoch_and_socket_source_match(app,login,enroll):
    headers,item=setup(app,login,enroll)
    other,_=enroll('router-a2')
    assert complete(app,{},item).status_code==401
    assert complete(app,other,item).status_code==409
    for change in [{'peer_ip':'192.0.2.140'},{'mac':'02:00:00:00:00:02'},{'epoch':'old'},
                   {'boot_id':'old-boot'},{'origin':'https://evil.example'},{'source_age_seconds':11}]:
        assert complete(app,headers,item,**change).status_code in {403,409}
    assert exam(app,'consume',proof_id=item['id']).status_code==409
    with app.app_context():assert db.session.query(NetworkSession).count()==0


def test_expiration_source_failure_and_disabled_endpoint_fail_closed(app,login,enroll):
    headers,item=setup(app,login,enroll)
    sync(app,headers,observation(sequence=1,complete=False,devices=[],source_error='router_offline'))
    assert complete(app,headers,item).status_code==409
    sync(app,headers,observation(sequence=2))
    response=login(1).put('/api/v1/routers/router-a/browser-proof',headers=CSRF,
        json={'version':1,'origin':ENDPOINT,'enabled':False})
    assert response.status_code==200
    assert complete(app,headers,item).status_code==409
    app.clock.value+=timedelta(seconds=46)
    assert complete(app,headers,item).status_code==409


def test_admin_only_endpoint_configuration_and_room_authorization(app,login,enroll):
    headers,item=setup(app,login,enroll)
    assert login(2).get('/api/v1/routers/router-a/browser-proof').status_code==403
    assert exam(app,'start',room_id='room-b').status_code==404
    assert exam(app,'start',user_id=5).status_code==403
    for origin in ['http://192.168.2.54:18766','https://localhost:18766','https://127.0.0.1:18766',
                   'https://example.com:invalid','https://exam.geekclass.ru','https://lan.local/path']:
        assert login(1).put('/api/v1/routers/router-a/browser-proof',headers=CSRF,
            json={'version':1,'origin':origin,'enabled':True}).status_code==400


def test_existing_other_user_is_not_silently_replaced(app,login,enroll):
    headers,item=setup(app,login,enroll)
    response=login(1).post('/api/v1/devices/'+device_id(app)+'/binding',headers=CSRF,
        json={'epoch':'connection-1','confirmed':True,'user_id':5})
    assert response.status_code==201
    assert complete(app,headers,item).status_code==409


def test_revoked_teacher_scope_and_changed_connection_invalidate_completed_proof(app,login,enroll):
    headers,item=setup(app,login,enroll)
    assert complete(app,headers,item).status_code==200
    sync(app,headers,observation(sequence=1,devices=[]))
    assert exam(app,'consume',proof_id=item['id']).status_code==409


def test_additive_schema_upgrade_is_idempotent_and_preserves_existing_routers(app):
    from guard_service.models import BrowserProof,LocalProofEndpoint,Router
    with app.app_context():
        BrowserProof.__table__.drop(db.engine)
        LocalProofEndpoint.__table__.drop(db.engine)
        before=db.session.query(Router).count()
    for _ in range(2):
        result=app.test_cli_runner().invoke(args=['upgrade-browser-proof-schema'])
        assert result.exit_code==0,result.output
    with app.app_context():assert db.session.query(Router).count()==before


def test_teacher_scope_revoked_before_completion_and_identity_expired_before_consumption(app,login,enroll):
    from guard_service.models import TeacherRoom,User
    headers,item=setup(app,login,enroll)
    with app.app_context():
        membership=db.session.get(TeacherRoom,('room-a',2));db.session.delete(membership);db.session.commit()
    assert complete(app,headers,item).status_code==404
    with app.app_context():
        db.session.add(TeacherRoom(room_id='room-a',user_id=2));db.session.commit()
    assert complete(app,headers,item).status_code==200
    with app.app_context():
        db.session.get(User,4).role_expires_at=app.clock()-timedelta(seconds=1);db.session.commit()
    assert exam(app,'consume',proof_id=item['id']).status_code==409
