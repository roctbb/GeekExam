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
from routes.callbacks import callbacks_bp
from routes.tests import tests_bp
from socket_events import register_socket_handlers
from celery_tasks.check_answer import (
    check_single_answer, check_attempt_answers, finish_expired_attempts,
    _finalize_attempt_if_done_inner,
)
from checkers.check_identity import versioned_callback_id
from validation import validate_answer
from attempt_lifecycle import finish_locked_attempt

TEST_DATABASE_URL = os.getenv('GEEKEXAM_TEST_DATABASE_URL', 'sqlite://')


class PlatformRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI=TEST_DATABASE_URL)
        db.init_app(self.app)
        for blueprint in (answers_bp, attempts_bp, callbacks_bp, tests_bp):
            self.app.register_blueprint(blueprint)
        self.socketio = SocketIO(self.app, async_mode='threading')
        register_socket_handlers(self.socketio)
        self.patch(patch.dict('sys.modules', {'manage': SimpleNamespace(app=self.app, socketio=self.socketio)}))
        self.enqueue_answer = self.patch(patch.object(check_single_answer, 'delay'))
        self.enqueue_attempt = self.patch(patch.object(check_attempt_answers, 'delay'))
        self.patch(patch('routes.callbacks._verify_callback_auth', return_value=None))
        self.patch(patch('routes.callbacks._is_duplicate_callback', return_value=False))
        self.patch(patch('routes.callbacks._mark_callback_processed'))
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
        return self.app.test_client().post('/api/callback/check', json={
            'callback_id': versioned_callback_id(1, self.state().value),
            'status': 'success', 'points': points, 'max_points': 10,
        })

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
        self.assertIsNone(self.state().total_points)
        self.assertIsNone(self.state().points)
        self.assertEqual(teacher.post('/api/answers/1/recheck').status_code, 422)
        self.assertEqual(self.callback().status_code, 200)
        self.assertEqual((self.state().points, self.state().total_points), (9, 9))
        self.assertTrue(self.state().is_checked)

    def test_failed_async_submission_finishes_instead_of_hanging(self):
        self.change(question={'check_type': 'ai'})
        self.finish()
        with patch('checkers.check_types.docker.DockerChecker.submit', return_value=(False, 'timeout')):
            check_single_answer.run(1)
        self.assertEqual((self.state().state, self.state().points, self.state().total_points), ('error', 0, 0))
        self.assertTrue(self.state().is_checked)

    def test_checker_exception_finishes_instead_of_hanging(self):
        self.finish()
        with patch('checkers.check_types.exact.ExactChecker.check', side_effect=RuntimeError('failed')):
            check_single_answer.run(1)
        self.assertEqual(self.state().state, 'error')
        self.assertTrue(self.state().is_checked)

    def test_late_success_after_submission_timeout_recalculates_total(self):
        self.change(question={'check_type': 'ai'})
        self.finish()
        with patch('checkers.check_types.docker.DockerChecker.submit', return_value=(False, 'timeout')):
            check_single_answer.run(1)
        self.assertEqual(self.state().total_points, 0)
        self.assertEqual(self.callback().status_code, 200)
        self.assertEqual(self.state().total_points, 9)

    def test_late_callback_cannot_overwrite_teacher_grade(self):
        self.change(question={'check_type': 'ai'})
        self.finish()
        self.login(1, 'teacher').put('/api/answers/1/grade', json={'points': 5})
        self.assertTrue(self.callback().json['stale'])
        self.assertEqual((self.state().points, self.state().total_points), (5, 5))

    def test_submission_error_cannot_overwrite_an_already_received_callback(self):
        self.change(question={'check_type': 'ai'})
        self.finish()
        def callback_then_timeout(*args):
            self.assertEqual(self.callback().status_code, 200)
            return False, 'timeout'
        with patch('checkers.check_types.docker.DockerChecker.submit', side_effect=callback_then_timeout):
            check_single_answer.run(1)
        self.assertEqual((self.state().state, self.state().total_points), ('checked', 9))

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

    def test_intermediate_failure_after_finish_is_terminal(self):
        self.change(question={'check_type': 'ai'})
        def fail_during_finish(*args):
            self.finish()
            check_attempt_answers.run(1)
            return False, 'timeout'
        with patch('checkers.check_types.docker.DockerChecker.submit', side_effect=fail_during_finish):
            check_single_answer.run(1, intermediate=True)
        self.assertEqual(self.state().state, 'error')
        self.assertTrue(self.state().is_checked)

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
        self.assertEqual(teacher.post(f'/api/tests/{test_id}/activate').status_code, 200)

    def test_legacy_empty_test_cannot_be_activated_or_joined(self):
        with self.app.app_context():
            test = Test(title='Empty', code='EMPTY', created_by=1, is_active=True)
            db.session.add(test)
            db.session.commit()
            test_id = test.id
        self.assertEqual(self.login(1, 'teacher').post(f'/api/tests/{test_id}/activate').status_code, 422)
        self.assertEqual(self.client.post('/api/join', json={'code': 'EMPTY'}).status_code, 422)

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
