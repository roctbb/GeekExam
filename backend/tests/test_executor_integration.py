import copy
from datetime import datetime
import hashlib
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import jwt

from models import db, User, Test, Variant, Question, Attempt, Answer
from execution_models import ExecutionRun
from routes.answers import answers_bp
from routes.attempts import attempts_bp
from routes.executor import executor_bp
from routes.tests import tests_bp
from celery_tasks.check_answer import check_single_answer
from celery_tasks.execution import dispatch_execution, recover_executions
import executor_transport as transport

SECRET = 'executor-integration-secret-' * 3


class ExecutorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='test-session', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        for bp in (answers_bp, attempts_bp, executor_bp, tests_bp): self.app.register_blueprint(bp)
        self.socket = SimpleNamespace(emit=Mock())
        self.patch(patch.dict('sys.modules', {'manage': SimpleNamespace(app=self.app, socketio=self.socket)}))
        self.patch(patch('config.GEEKEXECUTOR_SECRET', SECRET))
        self.patch(patch('config.EXECUTOR_STORAGE_DIR', self.directory.name))
        self.patch(patch('config.EXECUTOR_CALLBACK_BASE_URL', 'https://exam.test'))
        self.queued = self.patch(patch.object(dispatch_execution, 'delay'))
        self.patch(patch.object(check_single_answer, 'delay'))
        with self.app.app_context():
            db.create_all()
            db.session.add_all([User(id=1, name='Teacher', role='teacher'), User(id=2, name='Student', role='student'), User(id=3, name='Other', role='student')])
            test = Test(title='Exam', created_by=1)
            variant = Variant(title='One', test=test)
            question = Question(variant=variant, title='Program', body='Public condition', type='code_input',
                max_points=3, check_type='docker', allow_intermediate_check=True, check_config={
                    'lang': 'python', 'score_step': 0.5, 'tests': [dict(input='1', expected='2'),
                        dict(input='SECRET INPUT', expected='SECRET EXPECTED', hidden=True)]})
            attempt = Attempt(test=test, variant=variant, user_id=2, max_points=3, finished_at=datetime.utcnow())
            answer = Answer(attempt=attempt, question=question, value={'code': 'print(2)', 'lang': 'python'})
            db.session.add_all([test, attempt, answer]); db.session.commit()

    def patch(self, patcher):
        value = patcher.start(); self.addCleanup(patcher.stop); return value

    def tearDown(self):
        with self.app.app_context(): db.session.remove(); db.drop_all(); db.engine.dispose()

    def client(self, user=2, role='student'):
        client = self.app.test_client()
        with client.session_transaction() as values: values.update(user_id=user, role=role)
        return client

    def run_check(self, intermediate=False):
        check_single_answer.run(1, intermediate=intermediate)
        with self.app.app_context(): return db.session.get(Answer, 1).latest_execution_id

    def signed(self, method, path, value=None, purpose=None, raw=None, **overrides):
        raw = raw if raw is not None else transport.json_bytes(value) if value is not None else b''
        purpose = purpose or ('execution-input' if path.endswith('/input') else 'execution-result')
        now = int(__import__('time').time())
        claims = dict(iss='geekexecutor', aud='geekexam', purpose=purpose, iat=now, exp=now + 60,
                      body_sha256=hashlib.sha256(raw).hexdigest())
        claims.update(overrides)
        token = jwt.encode(claims, SECRET, algorithm='HS256')
        return self.app.test_client().open(path, method=method, data=raw,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})

    def result(self, run_id, points=1):
        return dict(execution_id=run_id, state='partially done', points=points, comment='1 из 2 тестов пройдено',
            statistics=dict(tests_passed=points, tests_total=2, verdict='wrong_answer', details=[
                dict(ok=True, input=transport.inline('1'), expected=transport.inline('2'), got=transport.inline('2')),
                dict(ok=False, input=transport.inline('SECRET INPUT'), expected=transport.inline('SECRET EXPECTED'), got=transport.inline('SECRET ACTUAL'))]))

    def test_batch_recheck_preserves_grades_and_dispatches_after_commit(self):
        first = self.run_check()
        self.signed('POST', f'/api/executor/executions/{first}/result', self.result(first))
        self.queued.reset_mock()
        response = self.client(1, 'teacher').post('/api/attempts/1/recheck')
        self.assertEqual(response.status_code, 200)
        second = response.json['executions'][0]['execution_id']
        self.assertNotEqual(first, second)
        self.queued.assert_called_once_with(second)
        with self.app.app_context():
            self.assertEqual(db.session.get(Answer, 1).points, 1.5)
            self.assertEqual(db.session.get(Attempt, 1).total_points, 1.5)
            self.assertFalse(db.session.get(Attempt, 1).is_checked)

    def test_materials_keep_stable_question_identity_after_authoring_save(self):
        with self.app.app_context():
            # Exercise the pre-exam path which used to delete and recreate all questions.
            db.session.delete(db.session.get(Attempt, 1)); db.session.commit()
        teacher = self.client(1, 'teacher')
        upload = teacher.post('/api/questions/1/files', data={'file': (io.BytesIO(b'fixture'), 'data.csv')})
        self.assertEqual(upload.status_code, 201)
        file_id = upload.json['items'][0]['id']
        test = teacher.get('/api/tests/1').json
        payload = dict(title='Updated', variants=[dict(id=test['variants'][0]['id'], title='One', questions=[dict(
            test['variants'][0]['questions'][0], title='Updated question')])])
        self.assertEqual(teacher.put('/api/tests/1', json=payload).status_code, 200)
        updated = teacher.get('/api/tests/1').json
        self.assertEqual(updated['variants'][0]['questions'][0]['id'], 1)
        self.assertEqual(updated['source_json']['variants'][0]['questions'][0]['id'], 1)
        self.assertEqual(teacher.get(f'/api/questions/1/files/{file_id}').data, b'fixture')

    def test_exported_question_identities_do_not_prevent_import_as_a_new_test(self):
        teacher=self.client(1,'teacher')
        payload=teacher.get('/api/tests/1').json
        payload={'title':'Copy','variants':payload['variants']}
        result=teacher.post('/api/tests',json=payload)
        self.assertEqual(result.status_code,201)
        copy=teacher.get(f"/api/tests/{result.json['id']}").json
        self.assertNotEqual(copy['variants'][0]['questions'][0]['id'],1)

    def test_dispatch_snapshot_callback_fractional_score_and_duplicate(self):
        run_id = self.run_check()
        self.assertIsNotNone(run_id)
        self.queued.assert_called_once_with(run_id)
        snapshot = self.signed('GET', f'/api/executor/executions/{run_id}/input')
        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.json['task']['points'], 2)
        self.assertEqual(snapshot.json['files'][0]['artifact']['text'], 'print(2)')
        body = self.result(run_id)
        for _ in range(2): self.assertEqual(self.signed('POST', f'/api/executor/executions/{run_id}/result', body).status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Answer, 1).points, 1.5)
            self.assertEqual(db.session.get(Attempt, 1).total_points, 1.5)
            self.assertTrue(db.session.get(ExecutionRun, run_id).applied)
        events = [call for call in self.socket.emit.call_args_list if call.args[0] == 'answer_checked']
        self.assertEqual(len(events), 1)
        self.assertNotIn('SECRET', json.dumps(events[0].args[1]))
        changed = self.result(run_id, 0)
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{run_id}/result', changed).status_code, 409)

    def test_stale_intermediate_result_cannot_overwrite_new_answer(self):
        with self.app.app_context():
            db.session.get(Attempt, 1).finished_at = None; db.session.commit()
        first = self.run_check(True)
        self.client().put('/api/answers/1', json={'value': {'code': 'print(3)', 'lang': 'python'}})
        second = self.run_check(True)
        self.assertNotEqual(first, second)
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{first}/result', self.result(first)).status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Answer, 1).latest_execution_id, second)
            self.assertEqual(db.session.get(Answer, 1).check_state, 'checking')
            self.assertFalse(db.session.get(ExecutionRun, first).applied)
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{second}/result', self.result(second)).status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Answer, 1).points)
            self.assertEqual(db.session.get(Answer, 1).check_state, 'pending')
            db.session.get(Attempt, 1).finished_at = datetime.utcnow(); db.session.commit()
        self.assertNotEqual(self.run_check(), second)

    def test_snapshot_is_frozen_and_private_details_are_role_scoped(self):
        run_id = self.run_check()
        with self.app.app_context():
            question = db.session.get(Question, 1)
            question.check_config = {'lang': 'python', 'tests': [{'input': 'NEW', 'expected': 'NEW'}]}
            question.max_points = 100; db.session.commit()
        original = self.signed('GET', f'/api/executor/executions/{run_id}/input').json
        self.assertEqual(original['task']['test_config']['tests'][1]['input']['text'], 'SECRET INPUT')
        self.signed('POST', f'/api/executor/executions/{run_id}/result', self.result(run_id))
        with self.app.app_context(): self.assertEqual(db.session.get(Answer, 1).points, 1.5)
        student = self.client().get(f'/api/executions/{run_id}')
        self.assertEqual(student.status_code, 200)
        self.assertNotIn('SECRET', student.text)
        self.assertIn('SECRET EXPECTED', self.client(1, 'teacher').get(f'/api/executions/{run_id}').text)
        self.assertEqual(self.client(3).get(f'/api/executions/{run_id}').status_code, 403)
        claims = jwt.decode(student.json['subscription']['token'], SECRET, algorithms=['HS256'], audience='geekexecutor')
        self.assertEqual((claims['iss'], claims['purpose'], claims['execution_id']), ('geekexam', 'execution-subscribe', run_id))

    def test_signatures_expiry_progress_order_and_terminal_run(self):
        run_id = self.run_check()
        path = f'/api/executor/executions/{run_id}/progress'
        progress = dict(execution_id=run_id, sequence=2, phase='testing', completed=2, total=200)
        for claims in (dict(iss='codingprojects'), dict(aud='codingprojects'), dict(purpose='executor-admin'),
                       dict(body_sha256='0' * 64), dict(exp=1), dict(exp=int(__import__('time').time()) + 3600)):
            parameters = dict(purpose='execution-progress')
            parameters.update(claims)
            self.assertEqual(self.signed('POST', path, progress, **parameters).status_code, 401)
        self.assertEqual(self.signed('POST', path, progress, purpose='execution-progress').status_code, 200)
        progress['sequence'] = 1; progress['completed'] = 0
        self.signed('POST', path, progress, purpose='execution-progress')
        with self.app.app_context(): self.assertEqual(db.session.get(ExecutionRun, run_id).sequence, 2)
        self.signed('POST', f'/api/executor/executions/{run_id}/result', self.result(run_id))
        progress['sequence'] = 999
        self.signed('POST', path, progress, purpose='execution-progress')
        with self.app.app_context(): self.assertEqual(db.session.get(ExecutionRun, run_id).state, 'completed')

    def test_large_artifact_transfer_and_hidden_output_download_access(self):
        with self.app.app_context():
            question = db.session.get(Question, 1)
            cfg = copy.deepcopy(question.check_config); cfg['tests'][1]['input'] = 'SECRET' * 20000
            question.check_config = cfg; db.session.commit()
        run_id = self.run_check()
        snapshot = self.signed('GET', f'/api/executor/executions/{run_id}/input').json
        field = snapshot['task']['test_config']['tests'][1]['input']
        path = field['download_url'].replace('https://exam.test', '')
        self.assertEqual(self.app.test_client().get(path).data, b'SECRET' * 20000)
        digest = hashlib.sha256(b'OUTPUT' * 20000).hexdigest()
        response = self.signed('POST', '/api/executor/test-artifacts/status', {'ids': [digest]}, purpose='test-artifacts')
        self.assertEqual(response.json, {'missing': [digest]})
        self.assertEqual(self.signed('PUT', '/api/executor/test-artifacts/' + digest, purpose='test-artifact-upload', raw=b'OUTPUT' * 20000).status_code, 200)
        result = self.result(run_id)
        result['statistics']['details'][1]['got'] = dict(type='blob', blob_id=digest, sha256=digest, bytes=120000, truncated=False)
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{run_id}/result', result).status_code, 200)
        download = f'/api/executions/{run_id}/artifacts/{digest}'
        self.assertEqual(self.client().get(download).status_code, 403)
        self.assertEqual(self.client(1, 'teacher').get(download).data, b'OUTPUT' * 20000)

    def test_uploaded_files_are_owned_and_frozen_in_snapshot(self):
        with self.app.app_context():
            db.session.get(Attempt, 1).finished_at = None; db.session.commit()
        upload = self.client().post('/api/answers/1/files', data={'file': (io.BytesIO(b'print(2)'), 'main.py')})
        self.assertEqual(upload.status_code, 201)
        path = '/api/answers/1/files/' + upload.json['id']
        self.assertEqual(self.client().get(path).data, b'print(2)')
        self.assertEqual(self.client(3).get(path).status_code, 403)
        self.assertEqual(self.client().get('/api/answers/1/files').json['items'][0]['download_url'], path)
        self.assertEqual(self.client(3).post('/api/answers/1/files', data={'file': (io.BytesIO(b'x'), 'x.py')}).status_code, 403)
        self.client().put('/api/answers/1', json={'value': {'mode': 'files', 'files': [{'upload_id': upload.json['id']}]}})
        run_id = self.run_check(True)
        self.assertEqual(self.client().delete(path).status_code, 409)
        snapshot = self.signed('GET', f'/api/executor/executions/{run_id}/input').json
        self.assertEqual(snapshot['files'][0]['name'], 'main.py')
        self.client().put('/api/answers/1', json={'value': {'code': 'print(3)', 'lang': 'python'}})
        self.assertEqual(self.client().delete(path).status_code, 200)
        self.assertEqual(self.signed('GET', f'/api/executor/executions/{run_id}/input').json['files'][0]['name'], 'main.py')

    def test_ai_private_prompt_and_half_point_scale_are_preserved(self):
        with self.app.app_context():
            q = db.session.get(Question, 1); q.check_type = 'ai'
            q.check_config = dict(prompt='PRIVATE RUBRIC', score_step=0.5, lang='python')
            db.session.commit()
        run_id = self.run_check()
        snapshot = self.signed('GET', f'/api/executor/executions/{run_id}/input').json
        self.assertEqual(snapshot['task']['points'], 6)
        self.assertIn('PRIVATE RUBRIC', snapshot['task']['private_instructions'])
        value = dict(execution_id=run_id, state='partially done', points=5, comment='Feedback')
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{run_id}/result', value).status_code, 200)
        with self.app.app_context(): self.assertEqual(db.session.get(Answer, 1).points, 2.5)
        self.assertNotIn('PRIVATE RUBRIC', self.client().get('/api/my-attempts/1/results').text)

    def test_dispatch_outbox_recovers_after_network_failure(self):
        from celery.exceptions import Retry
        import requests
        run_id = self.run_check()
        with patch('executor_transport.dispatch', side_effect=requests.Timeout('offline')):
            with self.assertRaises(requests.Timeout): dispatch_execution.run(run_id)
        with self.app.app_context():
            run = db.session.get(ExecutionRun, run_id)
            self.assertIsNone(run.result_hash); self.assertIsNone(run.lease_until); self.assertIsNone(run.dispatched_at)
        self.queued.reset_mock(); recover_executions.run(); self.queued.assert_called_once_with(run_id)
        with patch('executor_transport.dispatch') as send:
            dispatch_execution.run(run_id); dispatch_execution.run(run_id)
            send.assert_called_once()

    def test_recheck_returns_subscription_immediately_and_outage_preserves_grade(self):
        first = self.run_check()
        self.signed('POST', f'/api/executor/executions/{first}/result', self.result(first))
        response = self.client(1, 'teacher').post('/api/answers/1/recheck')
        self.assertEqual(response.status_code, 200)
        second = response.json['executions'][0]['execution_id']
        self.assertNotEqual(first, second)
        with self.app.app_context(): self.assertEqual(db.session.get(Answer, 1).points, 1.5)
        outage = dict(execution_id=second, state='execution error', points=0, comment='Executor unavailable')
        self.assertEqual(self.signed('POST', f'/api/executor/executions/{second}/result', outage).status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Answer, 1).points, 1.5)
            self.assertEqual(db.session.get(Attempt, 1).total_points, 1.5)
        detail = self.client().get('/api/attempts/1')
        self.assertEqual(detail.json['executions'][0]['execution_id'], second)

    def test_redelivered_local_queue_message_keeps_the_previous_grade(self):
        first=self.run_check();self.signed('POST',f'/api/executor/executions/{first}/result',self.result(first))
        response=self.client(1,'teacher').post('/api/answers/1/recheck')
        second=response.json['executions'][0]['execution_id']
        check_single_answer.run(1)
        with self.app.app_context():
            answer=db.session.get(Answer,1)
            self.assertEqual(answer.points,1.5);self.assertEqual(answer.latest_execution_id,second)
        self.assertEqual(self.signed('POST',f'/api/executor/executions/{second}/result',self.result(second,2)).status_code,200)
        with self.app.app_context():self.assertEqual(db.session.get(Answer,1).points,3)

    def test_compilation_error_is_visible_and_retry_creates_a_new_run(self):
        with self.app.app_context():db.session.get(Attempt,1).finished_at=None;db.session.commit()
        run_id=self.run_check(intermediate=True)
        value=self.result(run_id,0);value['statistics'].update(verdict='compilation_error')
        value['statistics']['details'][0].update(error_type='compilation_error',error=transport.inline("main.cpp: expected ';'"))
        self.assertEqual(self.signed('POST',f'/api/executor/executions/{run_id}/result',value).status_code,200)
        snapshot=self.client().get(f'/api/executions/{run_id}').json
        self.assertIn("expected ';'",snapshot['comment'])
        self.assertEqual(snapshot['statistics']['verdict'],'compilation_error')
        with self.app.app_context():self.assertIsNone(db.session.get(Answer,1).points)
        response=self.client().post('/api/answers/1/check')
        self.assertEqual(response.status_code,200)
        self.assertNotEqual(response.json['executions'][0]['execution_id'],run_id)

    def test_finished_and_intermediate_results_cannot_overwrite_teacher_grade(self):
        run_id=self.run_check();value=self.result(run_id)
        self.signed('POST',f'/api/executor/executions/{run_id}/result',value)
        self.assertEqual(self.client(1,'teacher').put('/api/answers/1/grade',json={'points':2.5}).status_code,200)
        self.assertEqual(self.signed('POST',f'/api/executor/executions/{run_id}/result',value).status_code,200)
        changed=self.result(run_id,2)
        self.assertEqual(self.signed('POST',f'/api/executor/executions/{run_id}/result',changed).status_code,409)
        with self.app.app_context():self.assertEqual(db.session.get(Answer,1).points,2.5)

    def test_old_callback_is_not_registered_even_with_a_valid_legacy_token(self):
        now=int(__import__('time').time())
        token=jwt.encode({'service':'geekpaste','iat':now},SECRET,algorithm='HS256')
        result=self.app.test_client().post('/api/callback/check',json={'callback_id':1,'points':3},headers={'Authorization':'Bearer '+token})
        self.assertEqual(result.status_code,404)
        with self.app.app_context():self.assertIsNone(db.session.get(Answer,1).points)
