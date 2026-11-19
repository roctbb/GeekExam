"""Evidence scenarios use server clocks and complete independent Guard observations."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask
from guard_admission import Admission, record_binding
from models import db, User, Test, Variant, Attempt
from presence_models import PresenceConfig, PresenceEvent, AttemptPresence, PresenceClient, PresenceHeartbeat
from routes.presence import presence_bp
import routes.presence_auto
import presence_service as service
from time_utils import utc_iso


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.clock=datetime(2026,11,18,10)
        self.app=Flask(__name__)
        self.app.config.update(TESTING=True,SECRET_KEY='test',SQLALCHEMY_DATABASE_URI='sqlite://',PRESENCE_NOW=lambda:self.clock)
        db.init_app(self.app);self.app.register_blueprint(presence_bp)
        with self.app.app_context():
            db.create_all()
            db.session.add_all([User(id=1,name='Teacher',role='teacher'),User(id=2,name='Student',role='student'),User(id=3,name='Other',role='student')])
            test=Test(id=1,title='Test',created_by=1)
            variant=Variant(id=1,test=test,title='V')
            db.session.add(Attempt(id=1,test=test,variant=variant,user_id=2,started_at=self.clock,max_points=10))
            db.session.commit()
        self.student=self.login(2);self.teacher=self.login(1,'teacher')

    def tearDown(self):
        with self.app.app_context():db.session.remove();db.drop_all()

    def login(self,id,role='student'):
        client=self.app.test_client()
        with client.session_transaction() as session:session.update(user_id=id,role=role)
        return client

    def register(self):
        response=self.student.post('/api/attempts/1/presence/clients',json={})
        self.assertEqual(response.status_code,200)
        return {key:response.json[key] for key in ['client_id','token']}

    def beat(self,credentials,seq=1,client=None):
        return (client or self.student).post('/api/attempts/1/presence/heartbeat',json={**credentials,'sequence':seq,'visible':True})

    def setup_binding(self):
        credentials=self.register();self.beat(credentials)
        with self.app.app_context():
            config=db.session.get(PresenceConfig,1);config.guard_room_id='room';config.guard_room_name='409';config.require_guard=True;db.session.add(AttemptPresence(attempt_id=1,
                guard_session_id='session',bound_client_id=credentials['client_id'],binding_confirmed_at=self.clock,
                binding_observed_at=self.clock,guard_state='online'))
            db.session.commit()
            version = config.version
        with self.student.session_transaction() as session:
            session['guard_attempts'] = [[1, 2, version, 'session']]
        return credentials

    def observation(self,loss_at=None,recovered_at=None,mass=False,complete=True):
        events=[]
        if loss_at:
            events.append({'id':'loss','kind':'device_disconnected','session_id':'session','router_id':'router',
                'occurred_at':utc_iso(loss_at),'last_confirmed_at':utc_iso(loss_at-timedelta(seconds=5)),
                'batch':'b','batch_departed':4 if mass else 1,'batch_total':6})
        if recovered_at:events.append({'id':'recovery','kind':'device_reconnected','session_id':'session','router_id':'router','occurred_at':utc_iso(recovered_at)})
        return {'server_time':utc_iso(self.clock),'room':{'id':'room','routers':[]},'history_complete':complete,'events':events,
            'items':[{'session_id':'session','user_id':2,'state':'unbound' if recovered_at else 'offline' if loss_at else 'online',
                'since':utc_iso(loss_at),'last_confirmed_at':utc_iso(self.clock) if not loss_at else None}]}

    def ingest(self,data):
        with self.app.app_context():
            service.ingest_guard(db.session.get(PresenceConfig,1),[db.session.get(Attempt,1)],data,self.clock);db.session.commit()

    def events(self):
        with self.app.app_context():return [service.event_view(row) for row in db.session.execute(db.select(PresenceEvent)).scalars()]

    def test_owner_token_and_server_time_replay_boundaries(self):
        creds=self.register()
        self.assertEqual(self.beat(creds,client=self.teacher).status_code,403)
        self.assertEqual(self.beat({**creds,'token':'bad'}).status_code,403)
        self.assertEqual(self.beat(creds).status_code,200)
        at=self.clock;self.clock+=timedelta(seconds=30)
        self.assertTrue(self.beat(creds).json['replay'])
        with self.app.app_context():
            self.assertEqual(db.session.get(PresenceClient,creds['client_id']).last_seen_at,at)
            self.assertEqual(db.session.query(PresenceHeartbeat).count(),1)
        self.assertEqual(self.beat(creds,3).status_code,409)
        self.assertEqual(self.beat(creds,True).status_code,422)
        self.assertEqual(self.student.get('/api/tests/1/presence').status_code,403)

    def test_cached_online_is_not_post_departure_evidence(self):
        self.setup_binding();self.clock+=timedelta(seconds=5)
        self.ingest(self.observation(loss_at=self.clock))
        events=self.events()
        self.assertEqual(len(events),1);self.assertFalse(events[0]['review_required'])
        self.clock+=timedelta(seconds=30)
        with self.app.app_context():
            service.update_exam_gaps(db.session.get(Attempt,1),self.clock);db.session.commit()
        self.assertFalse(any(e['review_required'] for e in self.events()))

    def test_new_heartbeat_after_departure_is_sticky_review_signal(self):
        creds=self.setup_binding();self.clock+=timedelta(seconds=5);lost=self.clock
        self.ingest(self.observation(loss_at=lost))
        self.clock+=timedelta(seconds=1);self.beat(creds,2)
        event=self.events()[0]
        self.assertTrue(event['review_required']);self.assertEqual(event['exam_continued_at'],utc_iso(self.clock))
        self.assertEqual(event['details']['evidence_client_scope'], 'bound')
        self.clock+=timedelta(seconds=4);self.ingest(self.observation(loss_at=lost,recovered_at=self.clock))
        self.assertTrue(self.events()[0]['review_required']);self.assertIsNotNone(self.events()[0]['ended_at'])
        self.assertEqual(self.teacher.post('/api/presence/events/'+event['id']+'/review',json={'note':'Проверено'}).status_code,200)
        with self.app.app_context():self.assertIsNone(db.session.get(Attempt,1).total_points)
        self.assertEqual(self.teacher.get('/api/tests/1/presence').json['attempts'][0]['review_count'],0)

    def test_quick_loss_and_recovery_between_collector_polls(self):
        creds=self.setup_binding();lost=self.clock+timedelta(seconds=5)
        self.clock+=timedelta(seconds=6);self.beat(creds,2)
        recovered=self.clock+timedelta(seconds=2);self.clock+=timedelta(seconds=4)
        self.ingest(self.observation(loss_at=lost,recovered_at=recovered))
        self.assertTrue(self.events()[0]['review_required'])

    def test_heartbeat_only_after_recovery_does_not_trigger_review(self):
        creds=self.setup_binding();lost=self.clock+timedelta(seconds=5);recovered=self.clock+timedelta(seconds=7)
        self.clock+=timedelta(seconds=10);self.beat(creds,2)
        self.ingest(self.observation(loss_at=lost,recovered_at=recovered))
        self.assertFalse(self.events()[0]['review_required'])

    def test_mass_or_incomplete_history_does_not_trigger_individual_flag(self):
        creds=self.setup_binding();lost=self.clock+timedelta(seconds=5)
        self.clock+=timedelta(seconds=6);self.beat(creds,2)
        self.ingest(self.observation(loss_at=lost,mass=True))
        self.assertFalse(any(e['review_required'] for e in self.events()))
        self.assertTrue(any(e['kind']=='mass_disconnect' for e in self.events()))

    def test_guard_outage_is_classroom_unknown_without_departure(self):
        self.setup_binding();self.clock+=timedelta(seconds=5)
        with self.app.app_context():
            service.mark_guard_unavailable(db.session.get(PresenceConfig,1),[db.session.get(Attempt,1)],'guard_unavailable',self.clock)
            db.session.commit()
        self.assertEqual(self.events()[0]['kind'],'guard_service_unavailable')
        data=self.teacher.get('/api/tests/1/presence').json
        self.assertEqual(data['attempts'][0]['guard']['state'],'unknown')
        self.assertEqual(data['attempts'][0]['review_count'],0)

    def test_incomplete_history_and_wrong_identity_cannot_create_review_signal(self):
        creds=self.setup_binding();lost=self.clock+timedelta(seconds=5)
        self.clock+=timedelta(seconds=6);self.beat(creds,2)
        self.ingest(self.observation(loss_at=lost,complete=False))
        self.assertFalse(any(e['review_required'] for e in self.events()))
        data=self.observation(loss_at=lost)
        data['items'][0]['user_id']=3
        self.ingest(data)
        self.assertFalse(any(e['review_required'] for e in self.events()))

    def test_collector_turns_guard_transport_failure_into_classroom_event(self):
        self.setup_binding()
        from guard_client import GuardUnavailable
        with self.app.app_context(),patch('guard_client.call',side_effect=GuardUnavailable('guard_unavailable')):
            service.collect_test(db.session.get(PresenceConfig,1))
        self.assertEqual([e['kind'] for e in self.events()],['guard_service_unavailable'])

    def test_collector_rejects_malformed_response_without_partial_individual_events(self):
        self.setup_binding();self.clock+=timedelta(seconds=5)
        bad=self.observation(loss_at=self.clock)
        bad['events'].append({'kind':'device_disconnected','session_id':'session','occurred_at':'invalid'})
        with self.app.app_context(),patch('guard_client.call',return_value=bad):
            service.collect_test(db.session.get(PresenceConfig,1))
        self.assertEqual([e['kind'] for e in self.events()],['guard_service_unavailable'])

    def test_finished_attempt_closes_open_gaps(self):
        creds=self.setup_binding();self.clock+=timedelta(seconds=5)
        self.ingest(self.observation(loss_at=self.clock))
        self.clock+=timedelta(seconds=1);self.beat(creds,2)
        with self.app.app_context():
            attempt=db.session.get(Attempt,1);attempt.finished_at=self.clock
            service.finish_monitoring(attempt);db.session.commit()
        self.assertEqual(self.events()[0]['ended_at'],utc_iso(self.clock))
        self.assertEqual(self.beat(creds,3).status_code,410)

    def test_final_reconciliation_uses_only_pre_submission_evidence(self):
        creds=self.setup_binding();lost=self.clock+timedelta(seconds=5)
        self.clock+=timedelta(seconds=6);self.beat(creds,2)
        with self.app.app_context():
            db.session.get(Attempt,1).finished_at=self.clock;db.session.commit()
        self.clock+=timedelta(seconds=4)
        data=self.observation(loss_at=lost)
        data['events'].append({**data['events'][0],'id':'after-finish','occurred_at':utc_iso(self.clock)})
        with self.app.app_context(),patch('guard_client.call',return_value=data):
            service.collect_test(db.session.get(PresenceConfig,1))
        self.assertEqual(len(self.events()),1)
        self.assertTrue(self.events()[0]['review_required'])
        self.assertEqual(self.events()[0]['ended_at'],utc_iso(self.clock-timedelta(seconds=4)))

    def test_finished_attempt_rejects_late_heartbeat(self):
        creds=self.register()
        with self.app.app_context():
            db.session.get(Attempt,1).finished_at=self.clock;db.session.commit()
        self.assertEqual(self.beat(creds).status_code,410)
        self.assertEqual(self.student.post('/api/attempts/1/presence/clients',json=creds).status_code,410)

    def test_binding_requires_exact_user_current_client_and_fresh_guard_proof(self):
        creds=self.register()
        with self.app.app_context():
            config = db.session.get(PresenceConfig,1)
            config.guard_room_id, config.require_guard = 'room', True
            db.session.commit()
        candidate={'session_id':'s','user_id':2,'device_id':'d','router_id':'r','last_confirmed_at':utc_iso(self.clock)}
        payload={'session_id':'s','client_id':creds['client_id'],'confirmed':True}
        with patch('guard_client.call',return_value={'candidates':[candidate]}) as call:
            self.assertEqual(self.teacher.post('/api/attempts/1/presence/binding',json=payload).status_code,200)
            call.assert_called_with('rooms',1,room_id='room',user_id=2)
        with patch('guard_client.call',return_value={'candidates':[{**candidate,'user_id':3}]}):
            self.assertEqual(self.teacher.post('/api/attempts/1/presence/binding',json=payload).status_code,409)

    def test_snapshot_preserves_strict_admission_after_guard_is_disabled(self):
        self.setup_binding()
        url = '/api/tests/1/presence'
        with self.app.app_context():
            service.event(1, 'legacy-proof', 'binding_confirmed', self.clock, attempt_id=1,
                          details={'method': 'browser_lan_proof', 'proof_id': 'legacy', 'client_code': 'OLD'})
            db.session.commit()
        self.assertFalse(self.teacher.get(url).json['attempts'][0]['guard_admitted'])

        with self.app.app_context():
            attempt = db.session.get(Attempt, 1)
            config = db.session.get(PresenceConfig, 1)
            admission = Admission(attempt.test_id, attempt.user_id, config.version, config.guard_room_id, 1)
            stamp = utc_iso(self.clock)
            candidate = {'user_id': 2, 'authorized': True, 'method': 'browser_lan_proof',
                         'session_id': 'session', 'device_id': 'd', 'router_id': 'r',
                         'last_confirmed_at': stamp, 'proved_at': stamp}
            record_binding(attempt, admission, candidate, 'strict-proof')
            record_binding(attempt, admission, candidate, 'repeat-proof')
            db.session.commit()
            version = config.version
        strict = self.teacher.get(url).json['attempts'][0]
        self.assertTrue(strict['guard_admitted'])
        self.assertEqual(strict['event_count'], 2)

        response = self.teacher.put(url, json={'version': version, 'enabled': True,
                                              'room_id': None, 'require_guard': False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['config']['require_guard'])
        self.assertTrue(response.json['attempts'][0]['guard_admitted'])
        self.assertFalse(response.json['attempts'][0]['guard']['bound'])

    def test_config_cas_and_browser_origin(self):
        self.register()
        payload={'version':1,'enabled':True,'room_id':None}
        self.assertEqual(self.teacher.put('/api/tests/1/presence',json=payload,headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.teacher.put('/api/tests/1/presence',json={**payload,'enabled':False}).status_code,200)
        self.assertEqual(self.teacher.put('/api/tests/1/presence',json=payload).status_code,409)

    def test_guard_setting_is_opt_in_and_requires_an_available_room(self):
        url = '/api/tests/1/presence'
        settings = self.teacher.get(url + '/settings').json['config']
        self.assertFalse(settings['require_guard'])
        payload = {'version': settings['version'], 'enabled': True, 'room_id': None, 'require_guard': True}
        self.assertEqual(self.teacher.put(url, json=payload).status_code, 422)
        with patch('guard_client.call', return_value={'room': {'name': 'Кабинет'}}) as call:
            configured = self.teacher.put(url, json={**payload, 'room_id': 'room'})
        self.assertEqual(configured.status_code, 200)
        self.assertTrue(configured.json['config']['require_guard'])
        call.assert_called_once_with('rooms', 1, room_id='room')
        with patch('guard_client.call') as call:
            disabled = self.teacher.put(url, json={**payload, 'room_id': 'room',
                'version': configured.json['config']['version'], 'require_guard': False})
            self.assertFalse(disabled.json['config']['require_guard'])
            with self.app.app_context():
                service.collect_test(db.session.get(PresenceConfig, 1))
            call.assert_not_called()

    def test_automatic_binding_requires_the_attempt_owner_and_exact_client(self):
        credentials=self.register()
        self.assertEqual(self.teacher.post('/api/attempts/1/presence/auto/start',json=credentials).status_code,403)
        self.assertEqual(self.student.post('/api/attempts/1/presence/auto/start',json={**credentials,'token':'wrong'}).status_code,403)

    def test_automatic_binding_requires_guard_admission(self):
        credentials=self.register()
        with self.app.app_context():
            config = db.session.get(PresenceConfig, 1)
            config.guard_room_id, config.require_guard = 'room', True
            db.session.commit()
        with patch('guard_client.call') as call:
            response = self.student.post('/api/attempts/1/presence/auto/start', json=credentials)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json['error_code'], 'guard_authorization_required')
            call.assert_not_called()

    def test_auto_binding_does_not_replace_a_changed_network_session_within_same_attempt(self):
        credentials=self.setup_binding()
        with self.app.app_context():
            state=db.session.get(AttemptPresence,1);state.guard_device_id='d';state.guard_router_id='r';db.session.commit()
        candidate={'session_id':'new-session','device_id':'d','router_id':'r','user_id':2,'method':'browser_lan_proof','authorized':True,
            'last_confirmed_at':utc_iso(self.clock),'proved_at':utc_iso(self.clock)}
        with patch('guard_client.call',return_value=candidate):
            self.assertEqual(self.student.post('/api/attempts/1/presence/auto/finish',json={**credentials,'proof_id':'p'}).status_code,200)
        with patch('guard_client.call', return_value={**candidate, 'device_id': 'different'}):
            response = self.student.post('/api/attempts/1/presence/auto/finish', json={**credentials, 'proof_id': 'different'})
            self.assertEqual(response.json['state'], 'different_device')
        with self.app.app_context():self.assertEqual(db.session.get(AttemptPresence,1).guard_session_id,'session')

    def wifi_snapshot(self, lost, **options):
        data = self.observation(loss_at=lost, **options)
        data['room']['routers'] = [{'id': 'router', 'fresh': True, 'observed_at': utc_iso(self.clock)}]
        data['items'][0].update(router_id='router', device_id='device', reason='device_disconnected')
        return data

    def prepare_wifi_test(self):
        credentials = self.setup_binding()
        with self.app.app_context():
            state = db.session.get(AttemptPresence, 1)
            state.guard_router_id, state.guard_device_id = 'router', 'device'
            db.session.commit()
        return credentials

    def test_wifi_grace_uses_router_time_and_persists_one_alert_without_an_exam_heartbeat(self):
        import wifi_alerts
        from presence_models import ExamWifiAlert
        self.prepare_wifi_test()
        with self.app.app_context():
            db.session.add(User(id=4, role='teacher', name='Class teacher'))
            db.session.flush()
            db.session.get(Test, 1).activated_by = 4
            db.session.commit()
        lost = self.clock + timedelta(seconds=1)
        self.clock = lost + timedelta(seconds=19)
        stale = self.wifi_snapshot(lost)
        self.ingest(stale)
        self.clock += timedelta(seconds=5)
        stale['server_time'] = utc_iso(self.clock)
        self.ingest(stale)
        self.assertIsNone(self.events()[0]['notification_status'])
        self.ingest(self.wifi_snapshot(lost))
        self.ingest(self.wifi_snapshot(lost))
        with self.app.app_context():
            alert = db.session.query(ExamWifiAlert).one()
            self.assertEqual(alert.payload, dict(teacher_id=4, student_name='Student', test_title='Test',
                room_name='409', event_id=alert.event_id, disconnected_at=utc_iso(lost)))
            with patch('wifi_alerts.send', side_effect=[('retry', 30), ('sent', 0)]) as send:
                self.assertTrue(wifi_alerts.deliver_next(self.clock))
                self.assertFalse(wifi_alerts.deliver_next(self.clock + timedelta(seconds=29)))
                self.assertTrue(wifi_alerts.deliver_next(self.clock + timedelta(seconds=30)))
                self.assertEqual(send.call_args_list[0], send.call_args_list[1])
                self.assertFalse(wifi_alerts.deliver_next(self.clock + timedelta(hours=1)))
        self.assertEqual(self.events()[0]['notification_status'], 'sent')

    def test_wifi_guard_outage_mass_recovery_identity_and_finished_attempt_suppress_alerts(self):
        from copy import deepcopy
        from presence_models import ExamWifiAlert
        self.prepare_wifi_test()
        lost = self.clock + timedelta(seconds=1)
        self.clock = lost + timedelta(seconds=25)
        good = self.wifi_snapshot(lost)
        variants = [self.wifi_snapshot(lost, complete=False)]
        for key, value in [('user_id', 3), ('device_id', 'other'), ('router_id', 'other'),
                           ('state', 'unknown'), ('reason', 'binding_revoked')]:
            data = deepcopy(good)
            data['items'][0][key] = value
            variants.append(data)
        bad_router = deepcopy(good)
        bad_router['room']['routers'][0].update(fresh=False)
        variants.append(bad_router)
        for sample in variants:
            self.ingest(sample)
        mass = self.wifi_snapshot(lost, mass=True)
        mass['events'][0]['id'] = 'mass-loss'
        self.ingest(self.wifi_snapshot(lost, recovered_at=lost + timedelta(seconds=8)))
        self.ingest(mass)
        with self.app.app_context():
            self.assertEqual(db.session.query(ExamWifiAlert).count(), 0)
            db.session.get(Attempt, 1).finished_at = self.clock
            db.session.commit()
        self.ingest(self.wifi_snapshot(lost + timedelta(seconds=1)))
        with self.app.app_context():
            self.assertEqual(db.session.query(ExamWifiAlert).count(), 0)

    def test_non_strict_test_has_no_wifi_alert_and_strict_setting_enables_monitoring(self):
        from presence_models import ExamWifiAlert
        self.prepare_wifi_test()
        with self.app.app_context():
            config = db.session.get(PresenceConfig, 1)
            config.require_guard = False
            db.session.commit()
            version = config.version
        lost = self.clock
        self.clock += timedelta(seconds=24)
        self.ingest(self.wifi_snapshot(lost))
        with self.app.app_context():
            self.assertEqual(db.session.query(ExamWifiAlert).count(), 0)
        with patch('guard_client.call', return_value={'room': {'name': '409'}}):
            updated = self.teacher.put('/api/tests/1/presence', json={
                'require_guard': True, 'enabled': False, 'room_id': 'room', 'version': version})
        self.assertTrue(updated.json['config']['enabled'])

    def test_matching_device_can_renew_after_reconnect_and_alert_on_next_departure(self):
        creds = self.prepare_wifi_test()
        lost = self.clock
        self.clock += timedelta(seconds=20)
        self.ingest(self.wifi_snapshot(lost))
        self.clock += timedelta(seconds=1)
        recovery = self.wifi_snapshot(lost, recovered_at=self.clock)
        recovery['items'][0]['reason'] = 'connection_changed'
        self.ingest(recovery)
        self.assertTrue(self.beat(creds, 2).json['renew_binding'])
        proof = dict(user_id=2, device_id='device', router_id='router', session_id='renewed',
            method='browser_lan_proof', authorized=True, last_confirmed_at=utc_iso(self.clock), proved_at=utc_iso(self.clock))
        with patch('guard_client.call', return_value=proof):
            result = self.student.post('/api/attempts/1/presence/auto/finish', json={**creds, 'proof_id': 'proof2'})
            self.assertEqual(result.json['state'], 'bound')
        self.assertFalse(self.beat(creds, 3).json['renew_binding'])
        renewal = next(e for e in self.events() if e['kind'] == 'binding_confirmed')
        self.assertEqual(renewal['details']['client_code'], creds['client_id'][:8].upper())
        lost = self.clock + timedelta(seconds=1)
        self.clock = lost + timedelta(seconds=20)
        again = self.wifi_snapshot(lost)
        again['items'][0]['session_id'] = 'renewed'
        again['events'][0].update(session_id='renewed', id='loss2')
        self.ingest(again)
        self.assertEqual(sum(e['notification_status'] == 'pending' for e in self.events()), 2)

    def test_finished_attempt_and_expired_proof_cannot_auto_bind(self):
        credentials=self.register()
        with self.app.app_context():
            db.session.get(Attempt,1).finished_at=self.clock;db.session.commit()
        self.assertEqual(self.student.post('/api/attempts/1/presence/auto/start',json=credentials).status_code,410)


if __name__=='__main__':unittest.main()
