from datetime import timedelta

from guard_service.models import db,Router
from conftest import observation


def test_handover_is_router_scoped_read_only_and_contains_no_access_grants(app,enroll):
    headers,_=enroll('router-a');other,_=enroll('router-b')
    client=app.test_client()
    assert client.post('/api/v1/agent/sync',headers=headers,json=observation()).status_code==200
    response=client.post('/api/v1/agent/handover',headers=headers,json={})
    assert response.status_code==200
    assert response.json['boot_id']=='boot-one'
    assert response.json['next_sequence']==1
    assert set(response.json['devices'][0])=={'mac','ip','epoch','interface'}
    with app.app_context():assert db.session.get(Router,'router-a').last_sequence==0
    assert client.post('/api/v1/agent/handover',headers=other,json={}).status_code==409
    assert client.post('/api/v1/agent/handover',json={}).status_code==401
    assert client.post('/api/v1/agent/handover',headers=headers,json={'router_id':'router-b'}).status_code==400
    app.clock.value+=timedelta(seconds=21)
    assert client.post('/api/v1/agent/handover',headers=headers,json={}).status_code==409
