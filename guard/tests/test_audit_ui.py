from datetime import timedelta

import pytest

from guard_service.models import (db, AuditEvent, Device, NetworkSession, Room,
                                  StudentRoom, TeacherRoom, User)
from guard_service.routes import audit

CSRF = {'X-CSRF-Token': 'test-csrf'}


def test_audit_pages_are_complete_room_scoped_and_stable_when_new_events_arrive(app, login):
    with app.app_context():
        for index in range(145):
            db.session.add(AuditEvent(id=f'action-{index:03}', room_id='room-a', event='session.portal_authenticated',
                target_id='deleted-session', actor_id=4, created_at=app.clock()-timedelta(seconds=index+1)))
        for index in range(205):
            db.session.add(AuditEvent(id=f'report-{index}', room_id='room-a', event='policy.reported',
                target_id='router-a', details={'revision': index, 'verified': True}, created_at=app.clock()-timedelta(seconds=index+1)))
        db.session.add(AuditEvent(room_id='room-b', event='room.created', target_id='room-b'))
        db.session.commit()
    client = login(2)
    first = client.get('/api/v1/rooms/room-a/audit?group=actions').json
    assert (first['total'], first['pages'], len(first['items'])) == (145, 8, 20)
    until = first['until']
    pages = [client.get('/api/v1/rooms/room-a/audit', query_string={
        'group': 'actions', 'page': page, 'until': until}).json for page in range(1, 9)]
    ids = [item['id'] for page in pages for item in page['items']]
    assert len(ids) == len(set(ids)) == 145
    app.clock.value += timedelta(seconds=1)
    with app.app_context():
        db.session.add(AuditEvent(id='new-action', room_id='room-a', event='room.created',
                                 target_id='room-a', created_at=app.clock()))
        db.session.commit()
    stable = client.get('/api/v1/rooms/room-a/audit', query_string={'group': 'actions', 'page': 2, 'until': until}).json
    assert stable == pages[1]
    refreshed = client.get('/api/v1/rooms/room-a/audit?group=actions').json
    assert refreshed['total'] == 146 and refreshed['items'][0]['id'] == 'new-action'
    reports = client.get('/api/v1/rooms/room-a/audit?group=reports&page_size=50').json
    assert reports['total'] == 205 and len(reports['items']) == 50
    assert all(item['title'] == 'Правила применены' for item in reports['items'])
    assert client.get('/api/v1/rooms/room-b/audit').status_code == 404
    assert login(4).get('/api/v1/rooms/room-a/audit').status_code == 403


@pytest.mark.parametrize('query', ['page=0', 'page=-1', 'page=abc', 'page_size=101', 'page_size=0',
                                   'group=bad', 'until=bad', 'until=2026-11-19'])
def test_invalid_journal_queries_are_rejected(login, query):
    assert login(1).get('/api/v1/rooms/room-a/audit?'+query).status_code == 400


def device_session(app):
    device = Device(id='device-one', router_id='router-a', segment_id='segment-a',
                    mac='02:00:00:00:00:01', ip='10.1.30.14', name='MacBook', epoch='epoch-one')
    db.session.add(device); db.session.flush()
    binding = NetworkSession(id='session-one', device_id=device.id, user_id=4, boot_id='boot-one',
                             epoch=device.epoch, expires_at=app.clock()+timedelta(hours=1), created_by=1)
    db.session.add(binding); db.session.commit()
    return device, binding


def test_readable_history_keeps_the_original_device_address_after_dhcp_changes(app, login):
    with app.test_request_context():
        device, binding = device_session(app)
        audit('room-a', 'session.portal_authenticated', binding.id, actor=db.session.get(User, 4))
        db.session.commit()
        device.ip = '10.1.30.99'; device.name = 'Renamed'; db.session.commit()
    event = login(2).get('/api/v1/rooms/room-a/audit').json['items'][0]
    assert event['title'] == 'Вход в Wi-Fi через Coding Projects'
    assert event['actor'] == 'Ученик 409'
    assert event['description'] == 'Ученик 409 · MacBook · 10.1.30.14'
    assert '10.1.30.99' not in event['description']


def test_teacher_permissions_leave_students_and_network_authorizations_untouched(app, login):
    with app.app_context():
        device_session(app)
        version = db.session.get(Room, 'room-a').version
    url = '/api/v1/rooms/room-a/teachers'
    payload = {'version': version, 'teacher_ids': [3]}
    assert login(2).put(url, json=payload, headers=CSRF).status_code == 403
    assert login(1).put(url, json={**payload, 'teacher_ids': [4]}, headers=CSRF).status_code == 400
    assert login(1).put(url, json=payload).status_code == 403
    assert login(1).put(url, json=payload, headers=CSRF).status_code == 200
    assert login(2).get('/api/v1/rooms/room-a').status_code == 404
    assert login(3).get('/api/v1/rooms/room-a').status_code == 200
    assert login(1).put(url, json={**payload, 'teacher_ids': []}, headers=CSRF).status_code == 409
    with app.app_context():
        assert db.session.get(StudentRoom, ('room-a', 4))
        assert db.session.get(NetworkSession, 'session-one').revoked_at is None
        assert db.session.get(TeacherRoom, ('room-a', 3))
