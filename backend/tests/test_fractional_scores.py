import itertools
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from models import db, User, Test, Variant, Question, Attempt, Answer
from routes.answers import answers_bp
from routes.attempts import attempts_bp
from checkers.check_types.exact import ExactChecker
from checkers.scoring import round_points, valid_points
from celery_tasks.check_answer import check_single_answer


class FractionalScoringTests(unittest.TestCase):
    def test_every_correct_wrong_and_omitted_statement(self):
        checker = ExactChecker()
        correct = [True, False] * 4
        for states in itertools.product(range(3), repeat=8):
            answer = {'answers': [expected if s == 0 else not expected if s == 1 else None
                                  for expected, s in zip(correct, states)]}
            points, _ = checker.check(answer, {'correct': correct, 'score_step': 0.5}, 4)
            self.assertEqual(points, states.count(0) / 2)
            legacy, _ = checker.check(answer, {'correct': correct}, 4)
            self.assertEqual(legacy, round(states.count(0) / 2))

    def test_fractional_fields_and_manual_score_validation(self):
        self.assertEqual(ExactChecker().check({'a': 'yes'}, {
            'answers': {'a': 'yes', 'b': 'yes'}, 'score_step': 0.5,
        }, 1)[0], 0.5)
        for value in (0, 0.5, 1, 3.5, 4):
            self.assertTrue(valid_points(value, 4, {'score_step': 0.5}))
        for value in (True, False, -0.5, 0.25, 4.5, float('nan'), float('inf'), '0.5'):
            self.assertFalse(valid_points(value, 4, {'score_step': 0.5}))
        self.assertFalse(valid_points(0.5, 4))
        self.assertEqual(round_points(3.5, {'score_step': 0.5}), 3.5)
        self.assertEqual(round_points(3.5), 4)


class FractionalPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='fractional-test', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        for bp in (answers_bp, attempts_bp):
            self.app.register_blueprint(bp)
        self.socketio = SimpleNamespace(emit=Mock())
        for patcher in (
            patch.dict('sys.modules', {'manage': SimpleNamespace(app=self.app, socketio=self.socketio)}),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        with self.app.app_context():
            db.create_all()
            db.session.add_all([User(id=1, name='Teacher', role='teacher'), User(id=2, name='Student', role='student')])
            test = Test(title='Fractional', created_by=1, is_active=False)
            variant = Variant(title='One', test=test)
            question = Question(variant=variant, title='Statements', type='true_false_table', max_points=4,
                check_type='exact', check_config={'correct': [True] * 8, 'score_step': 0.5},
                ui_config={'statements': ['Statement'] * 8})
            attempt = Attempt(test=test, variant=variant, user_id=2, max_points=4, finished_at=datetime.utcnow())
            answer = Answer(attempt=attempt, question=question, value={'answers': [True] * 7 + [False]})
            db.session.add_all([test, attempt, answer]); db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.drop_all(); db.engine.dispose()

    def client(self, user=1, role='teacher'):
        client = self.app.test_client()
        with client.session_transaction() as s: s.update(user_id=user, role=role)
        return client

    def assert_saved(self, points):
        with self.app.app_context():
            db.session.expire_all()
            self.assertEqual(db.session.get(Answer, 1).points, points)
            self.assertEqual(db.session.get(Attempt, 1).total_points, points)
            self.assertTrue(db.session.get(Attempt, 1).is_checked)
        result = self.client(2, 'student').get('/api/my-attempts/1/results')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['total_points'], points)
        self.assertEqual(result.json['answers'][0]['points'], points)

    def test_automatic_grade_survives_storage_total_and_result_api(self):
        check_single_answer.run(1)
        self.assert_saved(3.5)

    def test_manual_half_point_grade_and_step_validation(self):
        self.assertEqual(self.client().put('/api/answers/1/grade', json={'points': 2.5}).status_code, 200)
        self.assert_saved(2.5)
        for value in (0.25, 4.5, True):
            self.assertEqual(self.client().put('/api/answers/1/grade', json={'points': value}).status_code, 422)

    def test_retired_callback_cannot_change_stored_scores(self):
        check_single_answer.run(1)
        result=self.client().post('/api/callback/check',json={'callback_id':1,'status':'success','points':0,'max_points':8})
        self.assertEqual(result.status_code,404)
        self.assert_saved(3.5)
