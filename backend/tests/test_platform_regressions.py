import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_socketio import SocketIO

from models import db, User, Test, Variant, Question, Attempt, Answer
from routes.answers import answers_bp
from routes.attempts import attempts_bp
from routes.executor import executor_bp
from execution_models import ExecutionRun
from celery_tasks.execution import dispatch_execution
import executor_transport as transport
import hashlib, jwt, time, tempfile
from routes.tests import tests_bp
from socket_events import register_socket_handlers
from celery_tasks.check_answer import (
    check_single_answer, check_attempt_answers, finish_expired_attempts,
    _finalize_attempt_if_done_inner,
)
from validation import validate_answer
from attempt_lifecycle import finish_locked_attempt
from answer_limits import SHORT_FIELD_LIMIT, TEXT_LIMIT, CODE_LIMIT, REQUEST_LIMIT
from presence_models import AttemptPresence, PresenceConfig
from time_utils import utc_iso
from guard_client import GuardUnavailable

TEST_DATABASE_URL = os.getenv('GEEKEXAM_TEST_DATABASE_URL', 'sqlite://')


class PlatformRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI=TEST_DATABASE_URL)
        db.init_app(self.app)
        for blueprint in (answers_bp, attempts_bp, executor_bp, tests_bp):
            self.app.register_blueprint(blueprint)
        self.socketio = SocketIO(self.app, async_mode='threading')
        register_socket_handlers(self.socketio)
        self.patch(patch.dict('sys.modules', {'manage': SimpleNamespace(app=self.app, socketio=self.socketio)}))
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.secret='native-regression-secret-'*3
        self.patch(patch('config.GEEKEXECUTOR_SECRET',self.secret))
        self.patch(patch('config.EXECUTOR_STORAGE_DIR',self.directory.name))
        self.patch(patch.object(dispatch_execution,'delay'))
        self.enqueue_answer=self.patch(patch.object(check_single_answer,'delay'))
        self.enqueue_attempt=self.patch(patch.object(check_attempt_answers,'delay'))
        with self.app.app_context():
            db.create_all()
            db.session.add_all([User(id=1, name='Teacher', role='teacher'),
                                User(id=2, name='Student', role='student'),
                                User(id=3, name='Other', role='student')])
            test = Test(title='Test', created_by=1, code='TEST', is_active=True)
            variant = Variant(title='Variant', test=test)
            question = Question(variant=variant, title='Question', type='text_input', max_points=10,
                                check_type='exact', check_config={'answer': 'reference'}, ui_config={},
                                allow_intermediate_check=True)
            attempt = Attempt(test=test, variant=variant, user_id=2, max_points=10)
            answer = Answer(attempt=attempt, question=question, value={'text': 'reference'})
            db.session.add_all([test, attempt, answer])
            db.session.commit()
        self.client = self.login()

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def login(self, user_id=2, role='student'):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=user_id, role=role)
        return client

    def change(self, *, attempt=None, answer=None, question=None, test=None):
        with self.app.app_context():
            for model, changes in ((Attempt, attempt), (Answer, answer), (Question, question), (Test, test)):
                for key, value in (changes or {}).items():
                    setattr(db.session.get(model, 1), key, value)
            db.session.commit()

    def state(self):
        with self.app.app_context():
            attempt, answer = db.session.get(Attempt, 1), db.session.get(Answer, 1)
            return SimpleNamespace(finished_at=attempt.finished_at, is_checked=attempt.is_checked,
                                   total_points=attempt.total_points, state=answer.check_state,
                                   points=answer.points, value=answer.value)

    def finish(self):
        self.assertEqual(self.client.post('/api/attempts/1/finish').status_code, 200)

    def callback(self, points=9):
        with self.app.app_context():
            answer=db.session.get(Answer,1)
            run=db.session.get(ExecutionRun,answer.latest_execution_id)
            value=dict(execution_id=run.id,state='done',points=points,comment='Native result')
            path=f'/api/executor/executions/{run.id}/result'
        raw=transport.json_bytes(value);now=int(time.time())
        token=jwt.encode(dict(iss='geekexecutor',aud='geekexam',purpose='execution-result',iat=now,exp=now+60,body_sha256=hashlib.sha256(raw).hexdigest()),self.secret,algorithm='HS256')
        return self.app.test_client().post(path,data=raw,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})

    def test_references_require_finished_owned_attempt(self):
        response = self.client.get('/api/my-attempts/1/results')
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('reference', response.get_data(as_text=True))
        self.assertNotIn('check_config', self.client.get('/api/attempts/1').json['questions'][0])
        self.finish()
        self.assertEqual(self.client.get('/api/my-attempts/1/results').json['questions'][0]['check_config'],
                         {'answer': 'reference'})
        self.assertEqual(self.login(3).get('/api/my-attempts/1/results').status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/my-attempts/1/results').status_code, 401)

    def test_test_without_guard_opt_in_joins_without_contacting_guard(self):
        with self.app.app_context():
            db.session.add(PresenceConfig(test_id=1, guard_room_id='old-room', configured_by=1))
            db.session.commit()
        with patch('guard_client.call') as call:
            response = self.login(3).post('/api/join', json={'code': 'TEST'})
            self.assertEqual(response.status_code, 201)
            call.assert_not_called()

    def test_guard_proof_precedes_admission_and_is_bound_to_the_browser(self):
        with self.app.app_context():
            db.session.add(PresenceConfig(test_id=1, require_guard=True, guard_room_id='room', configured_by=1))
            db.session.commit()
        student = self.login(3)
        another_browser = self.login(3)
        code = {'code': 'TEST'}
        items = [{'id': 'proof', 'token': 'local-token', 'url': 'https://lan.example.test/v1/browser-proof'}]
        with patch('guard_client.call', return_value={'state': 'ready', 'items': items}) as start:
            first = student.post('/api/join', json=code)
            self.assertEqual(first.status_code, 202)
            self.assertEqual(start.call_args.args, ('proofs/start', 1))
            self.assertEqual(start.call_args.kwargs['test_id'], 1)
        ticket = {**code, 'guard_ticket': first.json['guard_proof']['ticket'], 'proof_ids': ['proof']}

        with patch('guard_client.call', side_effect=GuardUnavailable('proof_not_ready')) as consume:
            self.assertEqual(another_browser.post('/api/join', json=ticket).status_code, 403)
            consume.assert_not_called()
            refused = student.post('/api/join', json=ticket)
            self.assertEqual(refused.status_code, 403)
            self.assertEqual(refused.json['error_code'], 'guard_authorization_required')
        with self.app.app_context():
            self.assertIsNone(Attempt.query.filter_by(user_id=3).first())

        stamp = utc_iso(datetime.utcnow())
        proof = {'user_id': 3, 'authorized': True, 'method': 'browser_lan_proof', 'session_id': 'session',
                 'device_id': 'device', 'router_id': 'router', 'last_confirmed_at': stamp, 'proved_at': stamp}
        with patch('guard_client.call', return_value={**proof, 'authorized': False}):
            self.assertEqual(student.post('/api/join', json=ticket).status_code, 403)
        with patch('guard_client.call', return_value=proof):
            accepted = student.post('/api/join', json=ticket)
            self.assertEqual(accepted.status_code, 201)
        attempt_id = accepted.json['attempt_id']
        details = f'/api/attempts/{attempt_id}'
        first_detail = student.get(details).json
        self.assertTrue(first_detail['guard_required'])
        self.assertEqual(another_browser.get(details).status_code, 403)
        self.assertEqual(another_browser.post(details + '/finish').status_code, 403)
        answer_id = student.get(details).json['answers'][0]['id']
        self.assertEqual(another_browser.put(f'/api/answers/{answer_id}', json={'value': {'text': 'blocked'}}).status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.get(AttemptPresence, attempt_id).guard_session_id, 'session')
        with patch('guard_client.call', return_value={'state': 'ready', 'items': items}):
            resume = another_browser.post('/api/join', json=code).json['guard_proof']['ticket']
        with patch('guard_client.call', return_value={**proof, 'session_id': 'new-session'}):
            joined = another_browser.post('/api/join', json={**ticket, 'guard_ticket': resume})
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(joined.json['attempt_id'], attempt_id)
        self.assertEqual(another_browser.get(details).json['started_at'], first_detail['started_at'])
        self.assertEqual(student.get(details).status_code, 403)

    def test_guard_admission_rechecks_test_after_network_verification(self):
        with self.app.app_context():
            db.session.add(PresenceConfig(test_id=1, require_guard=True, guard_room_id='room', configured_by=1))
            db.session.commit()
        student = self.login(3)
        items = [{'id': 'proof', 'token': 'local-token', 'url': 'https://lan.example.test/v1/browser-proof'}]
        with patch('guard_client.call', return_value={'state': 'ready', 'items': items}):
            ticket = student.post('/api/join', json={'code': 'TEST'}).json['guard_proof']['ticket']

        def verify_after_stop(*_args, **_kwargs):
            self.change(test={'is_active': False})
            stamp = utc_iso(datetime.utcnow())
            return {'user_id': 3, 'authorized': True, 'method': 'browser_lan_proof', 'session_id': 'session',
                    'device_id': 'device', 'router_id': 'router', 'last_confirmed_at': stamp, 'proved_at': stamp}

        with patch('guard_client.call', side_effect=verify_after_stop):
            response = student.post('/api/join', json={'code': 'TEST', 'guard_ticket': ticket, 'proof_ids': ['proof']})
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            self.assertIsNone(Attempt.query.filter_by(user_id=3).first())

    def test_attempt_timestamps_have_explicit_utc_in_all_views(self):
        self.change(test={'time_limit': 5})
        detail = self.client.get('/api/attempts/1').json
        for key in ('started_at', 'server_time', 'time_deadline_at'):
            self.assertTrue(detail[key].endswith('Z'), key)
        self.finish()
        student = self.client.get('/api/my-attempts').json[0]
        teacher = self.login(1, 'teacher').get('/api/tests/1/attempts').json[0]
        result = self.client.get('/api/my-attempts/1/results').json
        for response in (student, teacher, result):
            self.assertEqual(response['started_at'], detail['started_at'])
            self.assertTrue(response['finished_at'].endswith('Z'))

    def test_test_results_rank_graded_questions_across_variants(self):
        finished_at = datetime.utcnow()
        self.change(attempt={'finished_at': finished_at, 'is_checked': True},
                    answer={'check_state': 'checked', 'points': 4.5},
                    question={'body': 'Условие первого варианта',
                              'check_config': {'answer': 'reference', 'private_instructions': 'internal'}})
        with self.app.app_context():
            test = db.session.get(Test, 1)
            original = db.session.get(Question, 1)
            second = Question(variant=original.variant, order=1, title='Second', type='text_input',
                              max_points=10, check_type='manual')
            other_variant = Variant(test=test, title='Other variant', order=1)
            other_question = Question(variant=other_variant, title=original.title, type='text_input',
                                      max_points=10, check_type='exact')
            unused_variant = Variant(test=test, title='Unused variant', order=2)
            unused_question = Question(variant=unused_variant, title='Third question', type='code_input',
                                       max_points=10, check_type='docker', check_config={'tests': [{'expected': '1'}]})
            perfect = Attempt(test=test, variant=original.variant, user_id=3, max_points=20,
                              finished_at=finished_at, is_checked=True)
            blank = Attempt(test=test, variant=other_variant, user_id=4, max_points=10,
                            finished_at=finished_at, is_checked=True)
            active = Attempt(test=test, variant=other_variant, user_id=5, max_points=10, is_checked=True)
            rechecking = Attempt(test=test, variant=other_variant, user_id=6, max_points=10,
                                 finished_at=finished_at)
            db.session.add_all([User(id=i, name=f'Student {i}', role='student') for i in (4, 5, 6)])
            db.session.add(unused_question)
            db.session.add_all([
                Answer(attempt_id=1, question=second, points=0, check_state='error'),
                Answer(attempt=perfect, question=original, points=10, check_state='checked'),
                Answer(attempt=perfect, question=second, points=10, check_state='checked'),
                Answer(attempt=blank, question=other_question, points=0, check_state='checked'),
                Answer(attempt=active, question=other_question, points=10, check_state='checked'),
                Answer(attempt=rechecking, question=other_question, points=10, check_state='checked'),
            ])
            db.session.commit()
            other_question_id, second_id, unused_question_id = other_question.id, second.id, unused_question.id

        url = '/api/tests/1/results'
        self.assertEqual(self.client.get(url).status_code, 403)
        teacher = self.login(1, 'teacher')
        results = teacher.get(url).json
        self.assertEqual(len(results['attempts']), 5)
        self.assertEqual(results['question_summary'], [
            dict(question_id=other_question_id, order=0, title='Question', variant_title='Other variant',
                 below_max_count=1, graded_count=1),
            dict(question_id=1, order=0, title='Question', variant_title='Variant',
                 below_max_count=1, graded_count=2),
            dict(question_id=second_id, order=1, title='Second', variant_title='Variant',
                 below_max_count=0, graded_count=1),
        ])
        review = results['question_review']
        self.assertEqual([group['order'] for group in review], [0, 1])
        variants = review[0]['variants']
        self.assertEqual([row['question_id'] for row in variants], [1, other_question_id, unused_question_id])
        self.assertEqual([(row['correct_count'], row['incorrect_count'], row['skipped_count']) for row in variants],
                         [(1, 1, 0), (0, 0, 1), (0, 0, 0)])
        details_url = '/api/tests/1/question-review/0'
        self.assertEqual(self.client.get(details_url).status_code, 403)
        self.assertEqual(teacher.get('/api/tests/2/question-review/0').status_code, 404)
        definitions = teacher.get(details_url).json['questions']
        self.assertEqual([question['id'] for question in definitions], [1, other_question_id, unused_question_id])
        self.assertEqual(definitions[0]['body'], 'Условие первого варианта')
        self.assertEqual(definitions[0]['check_config'], {'answer': 'reference'})
        self.assertEqual(definitions[2]['check_config'], {})

        self.assertEqual(teacher.put('/api/answers/1/grade', json={'points': 10}).status_code, 200)
        updated = teacher.get(url).json
        self.assertEqual(updated['question_summary'][1]['below_max_count'], 0)
        self.assertEqual(updated['question_review'][0]['variants'][0]['correct_count'], 2)

    def test_common_wrong_answers_use_the_same_grades_as_the_summary(self):
        finished_at = datetime.utcnow()
        self.change(attempt={'finished_at': finished_at, 'is_checked': True},
                    answer={'check_state': 'checked', 'points': 0, 'value': {'text': 'Синий'}})
        with self.app.app_context():
            question = db.session.get(Question, 1)
            for user_id, value, points, is_checked in (
                (3, {'text': ' синий  '}, 5, True),
                (4, {'text': '  ', 'mode': 'text', 'lang': 'text'}, 0, True),
                (5, {'text': 'синий'}, 10, True),
                (6, {'text': 'синий'}, 0, False),
            ):
                if user_id > 3:
                    db.session.add(User(id=user_id, name=f'Student {user_id}', role='student'))
                attempt = Attempt(test_id=1, variant=question.variant, user_id=user_id, max_points=10,
                                  finished_at=finished_at, is_checked=is_checked)
                db.session.add(Answer(attempt=attempt, question=question, value=value, points=points,
                                      check_state='checked'))
            db.session.commit()

        url = '/api/tests/1/questions/1/wrong-answers'
        self.assertEqual(self.client.get(url).status_code, 403)
        teacher = self.login(1, 'teacher')
        self.assertEqual(teacher.get('/api/tests/2/questions/1/wrong-answers').status_code, 404)
        result = teacher.get(url).json
        self.assertEqual(result['distinct_count'], 2)
        self.assertEqual(result['answers'][0], {'preview': 'Синий', 'count': 2, 'example_attempt_id': 1})
        self.assertIsNone(result['answers'][1]['preview'])
        summary = teacher.get('/api/tests/1/results').json['question_summary'][0]
        self.assertEqual(sum(row['count'] for row in result['answers']), summary['below_max_count'])
        self.assertEqual(teacher.get(url + '?include_skipped=0').json,
                         {'answers': result['answers'][:1], 'distinct_count': 1})

    def test_socket_rejects_anonymous_connections(self):
        self.assertFalse(self.socketio.test_client(self.app).is_connected())

    def test_socket_checks_room_owner_and_teacher_role(self):
        for user_id, role, allowed in [(2, 'student', True), (3, 'student', False),
                                       (1, 'teacher', True), (1, 'admin', True)]:
            with self.subTest(role=role, user=user_id):
                socket = self.socketio.test_client(self.app, flask_test_client=self.login(user_id, role))
                self.assertTrue(socket.is_connected())
                ack = socket.emit('join', {'room': 'attempt_1'}, callback=True)
                self.socketio.emit('answer_checked', {'checked_value': 'private'}, room='attempt_1')
                self.assertEqual(bool(socket.get_received()), allowed)
                self.assertEqual(ack, {'status': 'joined'} if allowed else {'error': 'Forbidden'})
                for data in [None, [], {}, {'room': '*'}, {'room': 'attempt_999'}, {'room': 1}]:
                    self.assertEqual(socket.emit('join', data, callback=True), {'error': 'Forbidden'})
                socket.disconnect()

    def test_result_list_socket_rooms_are_private_and_teacher_only(self):
        for user_id, role, room, allowed in [(2,'student','user_2',True),(3,'student','user_2',False),
                (2,'student','test_1',False),(1,'teacher','test_1',True),(1,'teacher','test_999',False)]:
            with self.subTest(user=user_id,room=room):
                socket=self.socketio.test_client(self.app,flask_test_client=self.login(user_id,role))
                ack=socket.emit('join',{'room':room},callback=True)
                self.assertEqual(ack,{'status':'joined'} if allowed else {'error':'Forbidden'})
                self.socketio.emit('attempt_list_updated',{'attempt_id':1},room=room)
                self.assertEqual(bool(socket.get_received()),allowed)
                socket.disconnect()

    def test_expired_save_finishes_at_deadline_without_accepting_value(self):
        started = datetime.utcnow() - timedelta(minutes=10)
        self.change(test={'time_limit': 1}, attempt={'started_at': started})
        response = self.client.put('/api/answers/1', json={'value': {'text': 'late'}})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.state().value, {'text': 'reference'})
        self.assertEqual(self.state().finished_at, started + timedelta(minutes=1))
        self.enqueue_attempt.assert_called_once_with(1)
        self.client.put('/api/answers/1', json={'value': None})
        self.enqueue_attempt.assert_called_once_with(1)

    def test_expired_intermediate_check_is_rejected(self):
        self.change(test={'time_limit': 1}, attempt={'started_at': datetime.utcnow() - timedelta(minutes=2)})
        self.assertEqual(self.client.post('/api/answers/1/check').status_code, 422)
        self.enqueue_answer.assert_not_called()
        self.assertIsNotNone(self.state().finished_at)

    def test_save_with_no_limit_or_before_deadline_still_works(self):
        for time_limit in [None, 10]:
            self.change(test={'time_limit': time_limit})
            self.assertEqual(self.client.put('/api/answers/1', json={'value': {'text': ''}}).status_code, 200)
            self.assertIsNone(self.state().finished_at)

    def test_expired_manual_finish_and_beat_use_actual_deadline(self):
        started = datetime.utcnow() - timedelta(minutes=2)
        self.change(test={'time_limit': 1}, attempt={'started_at': started})
        self.finish()
        self.assertEqual(self.state().finished_at, started + timedelta(minutes=1))
        self.assertEqual(self.client.post('/api/attempts/1/finish').status_code, 422)
        self.change(attempt={'finished_at': None})
        finish_expired_attempts.run()
        self.assertEqual(self.state().finished_at, started + timedelta(minutes=1))

    def test_single_recheck_invalidates_then_recalculates_total(self):
        self.change(question={'check_type': 'ai'}, attempt={'finished_at': datetime.utcnow(), 'is_checked': True,
                                                           'total_points': 2},
                    answer={'check_state': 'checked', 'points': 2})
        teacher = self.login(1, 'teacher')
        self.assertEqual(teacher.post('/api/answers/1/recheck').status_code, 200)
        self.assertFalse(self.state().is_checked)
        self.assertEqual(self.state().total_points,2)
        self.assertEqual(self.state().points,2)
        self.assertEqual(teacher.post('/api/answers/1/recheck').status_code, 422)
        self.assertEqual(self.callback().status_code, 200)
        self.assertEqual((self.state().points, self.state().total_points), (9, 9))
        self.assertTrue(self.state().is_checked)


    def test_checker_exception_finishes_instead_of_hanging(self):
        self.finish()
        with patch('checkers.check_types.exact.ExactChecker.check', side_effect=RuntimeError('failed')):
            check_single_answer.run(1)
        self.assertEqual(self.state().state, 'error')
        self.assertTrue(self.state().is_checked)


    def test_late_callback_cannot_overwrite_teacher_grade(self):
        self.change(question={'check_type': 'ai'})
        self.finish()
        self.assertEqual(self.callback().status_code,200)
        self.login(1, 'teacher').put('/api/answers/1/grade', json={'points': 5})
        self.assertEqual(self.callback().status_code,200)
        self.assertEqual((self.state().points, self.state().total_points), (5, 5))


    def test_teacher_is_notified_when_grading_becomes_available(self):
        socket = self.socketio.test_client(self.app, flask_test_client=self.login(1, 'teacher'))
        socket.emit('join', {'room': 'attempt_1'})
        self.finish()
        event = socket.get_received()[0]
        self.assertEqual(event['name'], 'attempt_finished')
        self.assertEqual(event['args'][0]['finished_at'], self.state().finished_at.isoformat() + 'Z')
        socket.disconnect()

    def test_finish_during_sync_intermediate_check_uses_final_result(self):
        def finish_during_check(*args):
            self.finish()
            check_attempt_answers.run(1)
            self.enqueue_answer.assert_not_called()
            return 7, 'Done'
        with patch('checkers.check_types.exact.ExactChecker.check', side_effect=finish_during_check):
            check_single_answer.run(1, intermediate=True)
        self.assertEqual((self.state().state, self.state().total_points), ('checked', 7))
        self.assertTrue(self.state().is_checked)
        # The final dispatch may arrive after the running check has already completed.
        check_attempt_answers.run(1)
        self.enqueue_answer.assert_not_called()
        self.assertEqual(self.state().total_points, 7)


    def test_intermediate_checks_keep_active_attempt_ungraded_including_empty_answers(self):
        for value in [None, {'text': 'reference'}]:
            self.change(answer={'value': value})
            check_single_answer.run(1, intermediate=True)
            self.assertEqual(self.state().state, 'pending')
            self.assertIsNone(self.state().points)
            self.assertFalse(self.state().is_checked)

    def test_old_sync_result_does_not_overwrite_new_answer(self):
        def edit_during_check(*args):
            self.assertEqual(self.client.put('/api/answers/1', json={'value': {'text': 'new'}}).status_code, 200)
            return 10, 'Old result'
        with patch('checkers.check_types.exact.ExactChecker.check', side_effect=edit_during_check):
            check_single_answer.run(1, intermediate=True)
        self.assertEqual(self.state().value, {'text': 'new'})
        self.assertEqual(self.state().state, 'pending')
        self.assertIsNone(self.state().points)

    def test_invalid_answer_shapes_are_rejected_without_replacing_saved_answer(self):
        for value in [[], ['bad'], 'bad', 5, {'text': []}, {'text': None}]:
            with self.subTest(value=value):
                self.assertEqual(self.client.put('/api/answers/1', json={'value': value}).status_code, 422)
                self.assertEqual(self.state().value, {'text': 'reference'})
        for body in [[], {'unrelated': 'value'}]:
            self.assertEqual(self.client.put('/api/answers/1', json=body).status_code, 422)

    def test_invalid_legacy_async_answer_becomes_error_instead_of_stuck_checking(self):
        self.change(question={'check_type': 'ai'}, answer={'value': ['bad legacy value']})
        self.finish()
        check_single_answer.run(1)
        self.assertEqual(self.state().state, 'error')
        self.assertTrue(self.state().is_checked)

    def test_unfinished_work_cannot_be_graded_or_rechecked(self):
        teacher = self.login(1, 'teacher')
        self.change(question={'check_type': 'manual'})
        self.assertEqual(teacher.put('/api/answers/1/grade', json={'points': 10}).status_code, 422)
        self.change(question={'check_type': 'ai'})
        self.assertEqual(teacher.post('/api/answers/1/recheck').status_code, 422)
        with self.app.app_context():
            db.session.get(Answer, 1).check_state = 'checked'
            db.session.commit()
            _finalize_attempt_if_done_inner(1, force_recalculate=True)
        self.assertFalse(self.state().is_checked)

    def test_grades_require_integer_points_in_range(self):
        self.finish()
        teacher = self.login(1, 'teacher')
        for points in [None, True, '5', -1, 11, 1000000, 1.5]:
            with self.subTest(points=points):
                self.assertEqual(teacher.put('/api/answers/1/grade', json={'points': points}).status_code, 422)
                self.assertIsNone(self.state().points)
        for points in [0, 10]:
            self.assertEqual(teacher.put('/api/answers/1/grade', json={'points': points}).status_code, 200)
            self.assertEqual(self.state().total_points, points)
        self.assertEqual(teacher.put('/api/answers/1/grade', json={'points': 5, 'comment': []}).status_code, 422)

    def test_grading_cannot_race_an_inflight_check(self):
        self.finish()
        self.change(answer={'check_state': 'checking'})
        self.assertEqual(self.login(1, 'teacher').put('/api/answers/1/grade', json={'points': 10}).status_code, 422)

    def test_partial_answer_drafts_and_custom_interactive_values_remain_valid(self):
        cases = [
            ('text_input', {}, {'text': ''}),
            ('code_input', {}, {'code': '', 'lang': 'python'}),
            ('multi_input', {'fields': [{'name': 'a'}]}, {'a': ''}),
            ('true_false_table', {'statements': ['a', 'b']}, {'answers': [False, None]}),
            ('choice_table', {'items': [{}], 'options': [{'value': 0}]}, {'answers': [0]}),
            ('matrix_input', {'size': 2}, {'matrix': [['', '0'], ['', '']], 'fields': {}}),
            ('interactive', {}, [1, 2]),
        ]
        for kind, ui, value in cases:
            with self.subTest(kind=kind):
                validate_answer(value, SimpleNamespace(type=kind, ui_config=ui, check_type='manual'))

    def test_answer_length_limits_reject_oversized_drafts_without_losing_saved_answer(self):
        for kind, value, limit in [
            ('text_input', lambda n: {'text': 'a' * n}, TEXT_LIMIT),
            ('code_input', lambda n: {'code': 'a' * n, 'lang': 'cpp'}, CODE_LIMIT),
            ('multi_input', lambda n: {'second': 'a' * n}, SHORT_FIELD_LIMIT),
            ('matrix_input', lambda n: {'matrix': [['a' * n]]}, SHORT_FIELD_LIMIT),
            ('interactive', lambda n: ['a' * n], CODE_LIMIT),
        ]:
            with self.subTest(kind=kind):
                self.change(question={'type': kind, 'ui_config': {'size': 1}, 'check_type': 'manual'})
                self.assertEqual(self.client.put('/api/answers/1', json={'value': value(limit)}).status_code, 200)
                before = self.state().value
                rejected = self.client.put('/api/answers/1', json={'value': value(limit + 1)})
                self.assertEqual(rejected.status_code, 422)
                self.assertIn('символов', rejected.json['error'])
                self.assertEqual(self.state().value, before)
        self.assertEqual(self.client.put('/api/answers/1', json={
            'value': ['x' * REQUEST_LIMIT]}).status_code, 413)

    def test_answer_limits_cover_unknown_fields_and_nested_interactive_data(self):
        for value in [{'text': 'ok', 'extra': 'x' * (TEXT_LIMIT + 1)},
                      {'text': '\U0001f600' * (TEXT_LIMIT // 2 + 1)}]:
            self.assertEqual(self.client.put('/api/answers/1', json={'value': value}).status_code, 422)
            self.assertEqual(self.state().value, {'text': 'reference'})
        self.change(question={'type': 'interactive', 'check_type': 'manual'})
        value = 'ok'
        for _ in range(22):
            value = [value]
        self.assertEqual(self.client.put('/api/answers/1', json={'value': value}).status_code, 422)



    def test_extending_55_to_70_adds_exactly_15_minutes_and_cannot_repeat_from_stale_page(self):
        started = datetime.utcnow() - timedelta(minutes=40)
        self.change(test={'time_limit': 55}, attempt={'started_at': started})
        before = self.client.get('/api/attempts/1').json
        teacher = self.login(1, 'teacher')
        payload = {'minutes': 15, 'expected_time_limit': 55}
        self.assertEqual(self.client.post('/api/tests/1/extend-time', json=payload).status_code, 403)
        response = teacher.post('/api/tests/1/extend-time', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['time_limit'], 70)
        after = self.client.get('/api/attempts/1').json
        self.assertEqual(datetime.fromisoformat(after['time_deadline_at']) -
                         datetime.fromisoformat(before['time_deadline_at']), timedelta(minutes=15))
        self.assertEqual(after['started_at'], before['started_at'])
        self.assertIsNone(after['finished_at'])
        self.assertEqual(teacher.post('/api/tests/1/extend-time', json=payload).status_code, 409)
        self.assertEqual(teacher.put('/api/tests/1/params', json={
            'title': 'Stale editor', 'time_limit': 55, 'expected_time_limit': 55}).status_code, 409)
        self.assertEqual(teacher.get('/api/tests/1').json['source_json']['time_limit'], 70)

    def test_absolute_limit_change_55_to_70_moves_deadline_by_15_minutes(self):
        self.change(test={'time_limit': 55})
        before = self.client.get('/api/attempts/1').json['time_deadline_at']
        response = self.login(1, 'teacher').put('/api/tests/1/params', json={
            'title': 'Test', 'time_limit': 70, 'expected_time_limit': 55})
        self.assertEqual(response.status_code, 200)
        after = self.client.get('/api/attempts/1').json['time_deadline_at']
        self.assertEqual(datetime.fromisoformat(after) - datetime.fromisoformat(before), timedelta(minutes=15))

    def test_stopping_test_finishes_active_work_and_notifies_student(self):
        socket = self.socketio.test_client(self.app, flask_test_client=self.client)
        socket.emit('join', {'room': 'attempt_1'})
        before = self.state().value
        response = self.login(1, 'teacher').post('/api/tests/1/deactivate')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['finished_attempts'], 1)
        self.assertIsNotNone(self.state().finished_at)
        self.assertEqual(self.state().value, before)
        self.enqueue_attempt.assert_called_once_with(1)
        self.assertEqual(socket.get_received()[0]['name'], 'attempt_finished')
        self.assertEqual(self.client.put('/api/answers/1', json={'value': {'text': 'late'}}).status_code, 422)
        self.assertEqual(self.login(3).post('/api/join', json={'code': 'TEST'}).status_code, 404)
        stopped_at = self.state().finished_at
        self.assertEqual(self.login(1, 'teacher').post('/api/tests/1/deactivate').json['finished_attempts'], 0)
        self.assertEqual(self.state().finished_at, stopped_at)
        socket.disconnect()

    def test_invalid_imports_are_rejected_and_valid_test_can_be_activated(self):
        teacher = self.login(1, 'teacher')
        valid = {'title': 'New', 'variants': [{'questions': [
            {'title': 'Q', 'type': 'text_input', 'check_type': 'exact', 'max_points': 1,
             'check_config': {'answer': 'yes'}},
        ]}]}
        invalid = [[], {'title': 'Empty', 'variants': []},
                   {'title': 'Empty', 'variants': [{'questions': []}]}]
        for path, value in [('time_limit', 0), ('time_limit', True), ('title', '')]:
            invalid.append({**valid, path: value})
        for key, value in [('max_points', -1), ('max_points', '1'), ('check_config', []), ('type', [])]:
            payload = copy.deepcopy(valid)
            payload['variants'][0]['questions'][0][key] = value
            invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(teacher.post('/api/tests', json=payload).status_code, 422)
                self.assertEqual(teacher.put('/api/tests/1', json=payload).status_code, 422)
        response = teacher.post('/api/tests', json=valid)
        self.assertEqual(response.status_code, 201)
        test_id = response.json['id']
        teacher.put(f'/api/tests/{test_id}/code', json={'code': 'NEW'})
        with self.app.app_context():
            db.session.add(User(id=4, name='Class teacher', role='teacher'))
            db.session.commit()
        leader = self.login(4, 'teacher')
        self.assertEqual(leader.post(f'/api/tests/{test_id}/activate').status_code, 200)
        self.assertEqual(teacher.post(f'/api/tests/{test_id}/activate').status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Test, test_id).activated_by, 4)

    def test_legacy_empty_test_cannot_be_activated_or_joined(self):
        with self.app.app_context():
            test = Test(title='Empty', code='EMPTY', created_by=1, is_active=True)
            db.session.add(test)
            db.session.commit()
            test_id = test.id
        self.assertEqual(self.login(1, 'teacher').post(f'/api/tests/{test_id}/activate').status_code, 422)
        self.assertEqual(self.client.post('/api/join', json={'code': 'EMPTY'}).status_code, 422)

    @unittest.skipUnless(TEST_DATABASE_URL.startswith('postgresql'), 'Requires PostgreSQL row locks')
    def test_stop_waits_for_admitted_student_and_finishes_the_new_attempt(self):
        locked, release, stopped = Event(), Event(), Event()
        joining = self.login(3)
        teacher = self.login(1, 'teacher')

        def choose(variants):
            locked.set()
            if not release.wait(5):
                raise AssertionError('Timed out waiting to admit student')
            return variants[0]

        def stop():
            response = teacher.post('/api/tests/1/deactivate')
            stopped.set()
            return response

        with patch('routes.attempts.random.choice', side_effect=choose), ThreadPoolExecutor(2) as pool:
            join_future = pool.submit(joining.post, '/api/join', json={'code': 'TEST'})
            try:
                self.assertTrue(locked.wait(5))
                stop_future = pool.submit(stop)
                self.assertFalse(stopped.wait(0.15))
            finally:
                release.set()
            self.assertEqual(join_future.result(timeout=5).status_code, 201)
            self.assertEqual(stop_future.result(timeout=5).json['finished_attempts'], 2)
        with self.app.app_context():
            self.assertEqual(Attempt.query.filter_by(finished_at=None).count(), 0)

    @unittest.skipUnless(TEST_DATABASE_URL.startswith('postgresql'), 'Requires PostgreSQL row locks')
    def test_finish_waits_for_answer_save_to_commit(self):
        locked, release, finish_done = Event(), Event(), Event()
        save_client, finish_client = self.login(), self.login()
        def validate_while_locked(*args):
            locked.set()
            if not release.wait(5):
                raise AssertionError('Timed out waiting to release the save')
            return validate_answer(*args)
        def finish():
            response = finish_client.post('/api/attempts/1/finish')
            finish_done.set()
            return response
        with patch('routes.answers.validate_answer', side_effect=validate_while_locked), ThreadPoolExecutor(2) as pool:
            save = pool.submit(save_client.put, '/api/answers/1', json={'value': {'text': 'last edit'}})
            try:
                self.assertTrue(locked.wait(5))
                finish_request = pool.submit(finish)
                self.assertFalse(finish_done.wait(0.15))
            finally:
                release.set()
            self.assertEqual(save.result(timeout=5).status_code, 200)
            self.assertEqual(finish_request.result(timeout=5).status_code, 200)
        self.assertEqual(self.state().value, {'text': 'last edit'})
        self.assertIsNotNone(self.state().finished_at)

    @unittest.skipUnless(TEST_DATABASE_URL.startswith('postgresql'), 'Requires PostgreSQL row locks')
    def test_save_waiting_for_finish_cannot_write_after_submission(self):
        locked, release, save_done = Event(), Event(), Event()
        save_client, finish_client = self.login(), self.login()
        def finish_while_locked(attempt):
            locked.set()
            if not release.wait(5):
                raise AssertionError('Timed out waiting to release the finish')
            return finish_locked_attempt(attempt)
        def save():
            response = save_client.put('/api/answers/1', json={'value': {'text': 'too late'}})
            save_done.set()
            return response
        with patch('routes.attempts.finish_locked_attempt', side_effect=finish_while_locked), ThreadPoolExecutor(2) as pool:
            finish_request = pool.submit(finish_client.post, '/api/attempts/1/finish')
            try:
                self.assertTrue(locked.wait(5))
                save_request = pool.submit(save)
                self.assertFalse(save_done.wait(0.15))
            finally:
                release.set()
            self.assertEqual(finish_request.result(timeout=5).status_code, 200)
            self.assertEqual(save_request.result(timeout=5).status_code, 422)
        self.assertEqual(self.state().value, {'text': 'reference'})


if __name__ == '__main__':
    unittest.main()
