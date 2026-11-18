from datetime import timedelta

from conftest import observation
from test_service import bind, sync, service_header
from guard_service.models import db, AuditEvent, NetworkSession
from guard_service.policy import stamp


def query(app, path, **values):
    return app.test_client().post('/api/v1/internal/exams/network/'+path,
        headers=service_header(app, 'EXAM_SERVICE_SECRET', 'guard:exams', 'geekexam'),
        json={'actor_id':2, **values})


def snap(app, session):
    response=query(app,'snapshot',room_id='room-a',session_ids=[session],since=stamp(app.clock()-timedelta(minutes=10)))
    assert response.status_code==200, response.json
    return response.json


def test_machine_api_scope_and_exact_student_candidates(app, login, enroll):
    headers,_=enroll('router-a')
    _,session=bind(app,login,headers)
    assert query(app,'rooms').json['items']==[{'id':'room-a','name':'409'}]
    assert query(app,'rooms',room_id='room-b').status_code==404
    candidates=query(app,'rooms',room_id='room-a',user_id=4).json['candidates']
    assert [c['session_id'] for c in candidates]==[session]
    assert query(app,'rooms',room_id='room-a',user_id=5).status_code==403
    assert app.test_client().post('/api/v1/internal/exams/network/rooms',json={'actor_id':2}).status_code==401
    assert query(app,'rooms',actor_id=4).status_code==403


def test_positive_departure_and_recovery_survive_polling_gap(app, login, enroll):
    headers,_=enroll('router-a')
    _,session=bind(app,login,headers)
    original=app.clock()
    assert snap(app,session)['items'][0]['state']=='online'
    app.clock.value+=timedelta(seconds=5)
    sync(app,headers,observation(sequence=1,devices=[]))
    offline=snap(app,session)
    assert offline['items'][0]['state']=='offline'
    loss=next(e for e in offline['events'] if e['kind']=='device_disconnected')
    assert loss['last_confirmed_at']==stamp(original)
    assert loss['occurred_at']==stamp(app.clock())
    app.clock.value+=timedelta(seconds=5)
    sync(app,headers,observation(sequence=2))
    recovered=snap(app,session)
    assert {e['kind'] for e in recovered['events']} >= {'device_disconnected','device_reconnected'}
    # Recovery does not silently reauthorize a revoked user-device binding.
    assert recovered['items'][0]['state']=='unbound'
    with app.app_context():
        assert db.session.get(NetworkSession,session).revoked_at is not None
        assert db.session.query(AuditEvent).filter_by(event='network.device_disconnected').count()==1


def test_source_outage_never_becomes_individual_departure(app, login, enroll):
    headers,_=enroll('router-a')
    _,session=bind(app,login,headers)
    app.clock.value+=timedelta(seconds=5)
    sync(app,headers,observation(sequence=1,devices=[],complete=False,source_error='router_unreachable'))
    data=snap(app,session)
    assert data['items'][0]['state']=='unknown'
    assert not any(e['kind']=='device_disconnected' for e in data['events'])
    app.clock.value+=timedelta(seconds=5)
    sync(app,headers,observation(sequence=2))
    kinds=[e['kind'] for e in snap(app,session)['events']]
    assert kinds.count('source_lost')==kinds.count('source_recovered')==1
    app.clock.value+=timedelta(seconds=21)
    assert snap(app,session)['items'][0]['state']=='unknown'


def test_revocation_or_expired_identity_is_unbound_not_physical_departure(app, login, enroll):
    headers,_=enroll('router-a')
    _,session=bind(app,login,headers)
    with app.app_context():
        db.session.get(NetworkSession,session).revoked_at=app.clock()
        db.session.commit()
    assert snap(app,session)['items'][0]['state']=='unbound'
    assert snap(app,'missing-session')['items'][0]['reason']=='unknown_session'
