import copy
import json
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from flask_migrate import Migrate, downgrade, stamp, upgrade
from sqlalchemy import inspect, text

from models import db, Answer, Attempt, Question, Test, TestGroup, User, Variant
from routes.tests import tests_bp


PAYLOAD = {
    'title': 'Системы счисления',
    'time_limit': 40,
    'variants': [{'title': 'Вариант 1', 'questions': [{
        'title': 'Переведите число', 'type': 'text_input', 'max_points': 5,
        'check_type': 'exact', 'check_config': {'answer': '42'},
    }]}],
}


class TestGroupApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='groups-test', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        self.app.register_blueprint(tests_bp)
        with self.app.app_context():
            db.create_all()
            db.session.add_all([User(id=1, name='Учитель', role='teacher'),
                                User(id=2, name='Ученик', role='student'),
                                User(id=3, name='Другой учитель', role='teacher')])
            db.session.commit()
        self.client = self.login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def login(self, user_id=1, role='teacher'):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=user_id, role=role)
        return client

    def group(self, name='7 класс'):
        response = self.client.post('/api/test-groups', json={'name': name})
        self.assertEqual(response.status_code, 201)
        return response.json['id']

    def create_test(self, **extra):
        response = self.client.post('/api/tests', json={**copy.deepcopy(PAYLOAD), **extra})
        self.assertEqual(response.status_code, 201)
        return response.json['id']

    def test_groups_can_be_created_renamed_and_listed_in_shared_catalog(self):
        group_id = self.group('  7 класс  ')
        other_teacher = self.login(3)
        self.assertEqual(other_teacher.get('/api/test-groups').json, [{'id': group_id, 'name': '7 класс'}])
        response = other_teacher.put(f'/api/test-groups/{group_id}', json={'name': '  8 класс  '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/test-groups').json, [{'id': group_id, 'name': '8 класс'}])

    def test_invalid_names_and_duplicate_names_do_not_change_groups(self):
        group_id = self.group()
        for name in ('', '   ', None, 7, [], 'x' * 121):
            with self.subTest(name=name):
                response = self.client.post('/api/test-groups', json={'name': name})
                self.assertEqual(response.status_code, 422)
                response = self.client.put(f'/api/test-groups/{group_id}', json={'name': name})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post('/api/test-groups', json={'name': ' 7 класс '}).status_code, 409)
        other = self.group('8 класс')
        self.assertEqual(self.client.put(f'/api/test-groups/{other}', json={'name': '7 класс'}).status_code, 409)
        self.assertEqual(len(self.client.get('/api/test-groups').json), 2)

    def test_new_tests_can_be_grouped_or_ungrouped_without_exporting_group_metadata(self):
        group_id = self.group()
        grouped = self.create_test(group_id=group_id)
        ungrouped = self.create_test()
        detail = self.client.get(f'/api/tests/{grouped}').json
        self.assertEqual(detail['group_id'], group_id)
        self.assertNotIn('group_id', detail['source_json'])
        tests = {test['id']: test for test in self.client.get('/api/tests').json}
        self.assertEqual(tests[grouped]['group_id'], group_id)
        self.assertIsNone(tests[ungrouped]['group_id'])

    def test_test_can_be_moved_between_groups_and_back_without_changing_results(self):
        group_id, other_group = self.group(), self.group('8 класс')
        test_id = self.create_test()
        with self.app.app_context():
            test = db.session.get(Test, test_id)
            test.code, test.is_active = 'SEVEN', True
            variant = test.variants[0]
            question = variant.questions[0]
            attempt = Attempt(test=test, variant=variant, user_id=2, max_points=5, total_points=4.5, is_checked=True)
            answer = Answer(attempt=attempt, question=question, value={'text': '42'}, points=4.5, check_state='checked')
            db.session.add_all([attempt, answer])
            db.session.commit()
            before = (test.source_json, variant.id, variant.questions[0].id, attempt.id, answer.id)
        for destination in (group_id, other_group, None):
            response = self.client.put(f'/api/tests/{test_id}/group', json={'group_id': destination})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['group_id'], destination)
            self.assertEqual(self.client.get(f'/api/tests/{test_id}').json['group_id'], destination)
        with self.app.app_context():
            test = db.session.get(Test, test_id)
            self.assertEqual(test.source_json, before[0])
            self.assertEqual((test.code, test.time_limit, test.is_active), ('SEVEN', 40, True))
            self.assertIsNotNone(db.session.get(Variant, before[1]))
            self.assertIsNotNone(db.session.get(Question, before[2]))
            self.assertEqual(db.session.get(Attempt, before[3]).total_points, 4.5)
            self.assertEqual(db.session.get(Answer, before[4]).value, {'text': '42'})

    def test_invalid_group_assignments_are_rejected_without_creating_or_moving_tests(self):
        group_id = self.group()
        test_id = self.create_test(group_id=group_id)
        for invalid in (True, False, '1', 1.0, -1, 0, 999, [], {}):
            with self.subTest(group_id=invalid):
                self.assertEqual(self.client.post('/api/tests', json={**PAYLOAD, 'group_id': invalid}).status_code, 422)
                self.assertEqual(self.client.put(f'/api/tests/{test_id}/group', json={'group_id': invalid}).status_code, 422)
        for invalid in ({}, [], 'group'):
            self.assertEqual(self.client.put(f'/api/tests/{test_id}/group', json=invalid).status_code, 422)
        self.assertEqual(len(self.client.get('/api/tests').json), 1)
        self.assertEqual(self.client.get(f'/api/tests/{test_id}').json['group_id'], group_id)

    def test_content_edits_and_json_imports_preserve_group_assignment(self):
        group_id = self.group()
        test_id = self.create_test(group_id=group_id)
        payload = copy.deepcopy(PAYLOAD)
        payload['title'] = 'Новое название'
        self.assertEqual(self.client.put(f'/api/tests/{test_id}', json=payload).status_code, 200)
        response = self.client.put(f'/api/tests/{test_id}/params', json={'title': 'Ещё название', 'time_limit': 55})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['group_id'], group_id)

    def test_deleting_group_keeps_tests_questions_attempts_and_answers(self):
        group_id, other = self.group(), self.group('8 класс')
        first = self.create_test(group_id=group_id)
        second = self.create_test(group_id=group_id)
        unaffected = self.create_test(group_id=other)
        with self.app.app_context():
            test = db.session.get(Test, first)
            variant = test.variants[0]
            question = variant.questions[0]
            attempt = Attempt(test=test, variant=variant, user_id=2, max_points=5, total_points=5)
            answer = Answer(attempt=attempt, question=question, value={'text': '42'}, points=5)
            db.session.add_all([attempt, answer])
            db.session.commit()
            attempt_id, answer_id = attempt.id, answer.id
        self.assertEqual(self.client.delete(f'/api/test-groups/{group_id}').status_code, 204)
        tests = {test['id']: test for test in self.client.get('/api/tests').json}
        self.assertIsNone(tests[first]['group_id'])
        self.assertIsNone(tests[second]['group_id'])
        self.assertEqual(tests[unaffected]['group_id'], other)
        with self.app.app_context():
            self.assertEqual(Question.query.count(), 3)
            self.assertEqual(db.session.get(Attempt, attempt_id).total_points, 5)
            self.assertEqual(db.session.get(Answer, answer_id).points, 5)

    def test_deleting_a_test_keeps_its_group(self):
        group_id = self.group()
        test_id = self.create_test(group_id=group_id)
        self.assertEqual(self.client.delete(f'/api/tests/{test_id}').status_code, 204)
        self.assertEqual(self.client.get('/api/test-groups').json, [{'id': group_id, 'name': '7 класс'}])

    def test_group_endpoints_require_teacher_or_admin(self):
        group_id = self.group()
        test_id = self.create_test()
        requests = [('/api/test-groups', 'get', None), ('/api/test-groups', 'post', {'name': '10 класс'}),
                    (f'/api/test-groups/{group_id}', 'put', {'name': '10 класс'}),
                    (f'/api/test-groups/{group_id}', 'delete', None),
                    (f'/api/tests/{test_id}/group', 'put', {'group_id': group_id})]
        for client, status in ((self.app.test_client(), 401), (self.login(2, 'student'), 403)):
            for url, method, body in requests:
                self.assertEqual(getattr(client, method)(url, json=body).status_code, status)
        self.assertEqual(self.login(1, 'admin').get('/api/test-groups').status_code, 200)

    def test_unknown_groups_and_tests_return_not_found(self):
        self.assertEqual(self.client.put('/api/test-groups/999', json={'name': 'X'}).status_code, 404)
        self.assertEqual(self.client.delete('/api/test-groups/999').status_code, 404)
        self.assertEqual(self.client.put('/api/tests/999/group', json={'group_id': None}).status_code, 404)


class TestGroupMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_existing_data_and_downgrade_preserves_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{directory}/migration.db'
            db.init_app(app)
            Migrate(app, db)
            migrations = str(Path(__file__).resolve().parents[1] / 'migrations')
            with app.app_context():
                # The tests/users schema is unchanged since the initial revision.
                # Skip historical PostgreSQL-specific answer FK migrations on SQLite.
                upgrade(directory=migrations, revision='6922f5f0bee0')
                stamp(directory=migrations, revision='d8a15f9c3b20')
                with db.engine.begin() as connection:
                    connection.execute(text("INSERT INTO users (id, name, role) VALUES (1, 'Teacher', 'teacher')"))
                    connection.execute(text("INSERT INTO tests (id, title, is_active, created_by, source_json) VALUES (1, 'Existing', 1, 1, :source)"), {'source': json.dumps(PAYLOAD)})
                upgrade(directory=migrations)
                test = db.session.get(Test, 1)
                self.assertEqual((test.title, test.is_active, test.group_id), ('Existing', True, None))
                self.assertEqual(json.loads(test.source_json), PAYLOAD)
                group = TestGroup(name='7 класс')
                db.session.add(group)
                db.session.flush()
                test.group = group
                db.session.commit()
                db.session.remove()
                downgrade(directory=migrations, revision='d8a15f9c3b20')
                self.assertNotIn('test_groups', inspect(db.engine).get_table_names())
                with db.engine.connect() as connection:
                    self.assertEqual(connection.execute(text('SELECT title, is_active FROM tests')).one(), ('Existing', 1))
                upgrade(directory=migrations)
                self.assertIsNone(db.session.get(Test, 1).group_id)
                db.session.remove()
                db.engine.dispose()
