import pytest

from guard_service.models import db, DeviceOverride, LocalProofEndpoint, NetworkLogin, Room, Router, User
from conftest import observation


def prepare(app, enroll):
    headers,_ = enroll('router-a')
    client = app.test_client()
    assert client.post('/api/v1/agent/sync',json=observation(),headers=headers).status_code == 200
    with app.app_context():
        db.session.add(LocalProofEndpoint(router_id='router-a',origin='https://lan.example.test:18766',enabled=True))
        db.session.commit()
    return client,headers


def begin(client):
    return client.post('/api/v1/network-login/start',json={'router_id':'router-a'},headers={'X-CSRF-Token':'test-csrf'})


def complete(agent,headers,token,**changes):
    payload={'token':token,'origin':'http://127.0.0.1:8088','endpoint_origin':'https://lan.example.test:18766',
             'peer_ip':'192.0.2.139','mac':'02:00:00:00:00:01','epoch':'connection-1','boot_id':'boot-one','source_age_seconds':0}
    return agent.post('/api/v1/agent/network-login/complete',json={**payload,**changes},headers=headers)


@pytest.mark.parametrize('user_id,role',[(1,'admin'),(2,'teacher'),(4,'student')])
def test_portal_assigns_actual_role_and_owner(app,login,enroll,user_id,role):
    agent,headers=prepare(app,enroll)
    client=login(user_id); proof=begin(client)
    assert proof.status_code==201
    assert complete(agent,headers,proof.json['token']).status_code==200
    state=client.get('/api/v1/network-login/'+proof.json['id']).json
    assert state['state']=='authenticated'
    assert state['device']['user']=={'id':user_id,'name':state['device']['user']['name'],'role':role}
    assert state['device']['profile']=='full'
    assert state['device']['binding_method']=='codingprojects_portal'
    other=login(5 if user_id!=5 else 4)
    assert other.get('/api/v1/network-login/'+proof.json['id']).status_code==404


def test_restricted_student_and_admin_device_exception(app,login,enroll):
    agent,headers=prepare(app,enroll)
    client=login(4); proof=begin(client).json
    with app.app_context():
        db.session.get(Room,'room-a').manual_restriction=True;db.session.commit()
    assert complete(agent,headers,proof['token']).status_code==200
    url='/api/v1/network-login/'+proof['id']
    state=client.get(url).json
    assert state['device']['profile']=='platform_only'
    device=state['device']['id']
    assert client.put(f'/api/v1/devices/{device}/override',json={'reason':'self grant'},headers={'X-CSRF-Token':'test-csrf'}).status_code==403
    with app.app_context():
        db.session.add(DeviceOverride(device_id=device,created_by=1,reason='Принтер'));db.session.commit()
    assert client.get(url).json['device']['profile']=='full'


@pytest.mark.parametrize('changes',[
    {'peer_ip':'192.0.2.140'}, {'mac':'02:00:00:00:00:02'}, {'epoch':'old'},
    {'boot_id':'old'}, {'source_age_seconds':11}, {'origin':'https://attacker.test'},
    {'endpoint_origin':'https://attacker.test'},
])
def test_portal_rejects_changed_or_forged_lan_evidence(app,login,enroll,changes):
    agent,headers=prepare(app,enroll)
    proof=begin(login(4)).json
    assert complete(agent,headers,proof['token'],**changes).status_code in (400,403,409)
    with app.app_context():assert db.session.get(NetworkLogin,proof['id']).session_id is None


def test_no_csrf_role_spoof_or_silent_account_switch(app,login,enroll):
    agent,headers=prepare(app,enroll)
    client=login(4)
    assert client.post('/api/v1/network-login/start',json={'router_id':'router-a'}).status_code==403
    assert client.post('/api/v1/network-login/start',json={'router_id':'router-a','role':'admin'},headers={'X-CSRF-Token':'test-csrf'}).status_code==400
    proof=begin(client).json
    assert complete(agent,headers,proof['token']).status_code==200
    second=begin(login(1)).json
    assert complete(agent,headers,second['token']).status_code==409
    app.clock.value += __import__('datetime').timedelta(seconds=46)
    assert complete(agent,headers,proof['token']).status_code==409


def test_portal_csp_allows_only_its_lan_endpoint_and_sso_returns_there(app,login,enroll):
    prepare(app,enroll)
    client=login(4)
    response=client.get('/connect/router-a')
    assert "connect-src 'self' https://lan.example.test:18766;" in response.headers['Content-Security-Policy']
    response=client.get('/auth/login?network=router-a&redirect=https://attacker.test')
    assert response.status_code==302
    with client.session_transaction() as state:assert state['login_next']=='/connect/router-a'


def test_logout_revokes_this_browser_network_session(app,login,enroll):
    agent,headers=prepare(app,enroll)
    client=login(4); proof=begin(client).json
    assert complete(agent,headers,proof['token']).status_code==200
    assert client.post('/auth/logout',headers={'X-CSRF-Token':'test-csrf'}).status_code==200
    state=login(1).get('/api/v1/rooms/room-a').json
    assert state['devices'][0]['user'] is None
    assert state['devices'][0]['profile']=='bootstrap'


def test_logout_cancels_an_automatic_confirmation_still_in_flight(app,login,enroll):
    agent,headers=prepare(app,enroll)
    client=login(4);proof=begin(client).json
    assert client.post('/auth/logout',headers={'X-CSRF-Token':'test-csrf'}).status_code==200
    assert complete(agent,headers,proof['token']).status_code==409
    assert login(1).get('/api/v1/rooms/room-a').json['devices'][0]['user'] is None


def test_same_origin_transport_is_explicitly_enabled_per_router(app,login,enroll):
    prepare(app,enroll)
    client=login(4)
    assert begin(client).json['url']=='https://lan.example.test:18766/v1/network-login'
    app.config['LAN_PROXY_ROUTERS']={'different-router'}
    assert begin(client).json['url']=='https://lan.example.test:18766/v1/network-login'
    app.config['LAN_PROXY_ROUTERS']={'router-a'}
    assert begin(client).json['url']=='/lan/router-a/network-login'


def test_room_study_mode_changes_only_access_and_keeps_the_student_login(app,login,enroll):
    agent,headers=prepare(app,enroll)
    pupil=login(4);proof=begin(pupil).json
    assert complete(agent,headers,proof['token']).status_code==200
    teacher=login(2)
    original=pupil.get('/api/v1/network-login/'+proof['id']).json
    session_id=original['device']['session_id']
    for restricted in [True,False,True]:
        room=teacher.get('/api/v1/rooms/room-a').json
        response=teacher.patch('/api/v1/rooms/room-a',json={'manual_restriction':restricted,'version':room['version']},headers={'X-CSRF-Token':'test-csrf'})
        assert response.status_code==200
        state=pupil.get('/api/v1/network-login/'+proof['id']).json
        assert state['state']=='authenticated'
        assert state['device']['session_id']==session_id
        assert state['device']['profile']==('platform_only' if restricted else 'full')
