import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from routes.attempts import attempts_bp


class AttemptReferenceAccessTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-only')
        app.register_blueprint(attempts_bp)
        self.client = app.test_client()
        question = SimpleNamespace(
            id=11, order=11, type='choice_table', title='Модули', body='Условие',
            max_points=2, check_type='exact', ui_config={},
            allow_intermediate_check=False, check_config={'correct': ['3']},
        )
        self.attempt = SimpleNamespace(
            id=1, user_id=10, test_id=31, variant_id=76,
            test=SimpleNamespace(title='Тест', time_limit=None),
            variant=SimpleNamespace(questions=[question]), answers=[],
            started_at=None, finished_at=None, is_checked=False,
            total_points=None, max_points=2,
        )

    def request(self, role, user_id=10):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['role'] = role
        model = SimpleNamespace(query=Mock())
        model.query.get_or_404.return_value = self.attempt
        with patch('routes.attempts.Attempt', model), patch('routes.attempts.db.session.get', return_value=None):
            return self.client.get('/api/attempts/1')

    def test_teacher_and_admin_receive_reference_for_another_students_attempt(self):
        for role in ('teacher', 'admin'):
            with self.subTest(role=role):
                response = self.request(role, user_id=99)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['questions'][0]['check_config'], {'correct': ['3']})

    def test_student_cannot_see_reference_while_taking_test(self):
        response = self.request('student')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('check_config', response.json['questions'][0])

    def test_native_submission_settings_exclude_private_grading_materials(self):
        q=self.attempt.variant.questions[0]
        q.type, q.check_type = 'code_input', 'ai'
        q.check_config = {'lang':'python','submission_modes':['files','project'], 'max_files':3,
            'private_instructions':'SECRET RUBRIC','reference_answer':'SECRET ANSWER','gpt_model':'PRIVATE MODEL'}
        result=self.request('student')
        self.assertEqual(result.status_code,200)
        cfg=result.json['questions'][0]['submission_config']
        self.assertEqual(cfg['submission_modes'],['files','project'])
        self.assertEqual(cfg['max_files'],3)
        self.assertNotIn('SECRET',result.text)
        self.assertNotIn('PRIVATE MODEL',result.text)

    def test_other_student_cannot_read_attempt(self):
        self.assertEqual(self.request('student', user_id=99).status_code, 403)

    def test_anonymous_cannot_read_attempt(self):
        self.assertEqual(self.client.get('/api/attempts/1').status_code, 401)


if __name__ == '__main__':
    unittest.main()
