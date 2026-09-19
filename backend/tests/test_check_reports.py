import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from checkers.check_identity import versioned_callback_id
from checkers.check_report import test_report
from routes.callbacks import callbacks_bp, _parse_callback_id


class CheckReportTests(unittest.TestCase):
    def test_detailed_report_and_hidden_test_data(self):
        report = test_report({'comment': '1 из 5 тестов пройдено', 'details': [
            {'ok': True}, {'ok': False, 'input': 'SECRET', 'expected': 'SECRET', 'got': 'SECRET'},
            {'ok': False, 'error': 'Execution timed out after 3 seconds.'},
            {'ok': False, 'error': 'Execution container stopped after a timeout.'},
            {'ok': False, 'error': 'ValueError: invalid literal'},
        ]}, {'tests': [{'name': 'Маленькие данные'}]})
        for expected in ['Маленькие данные: пройден', 'неверный ответ', 'превышен лимит времени',
                         'не выполнен', 'ValueError']:
            self.assertIn(expected, report)
        self.assertNotIn('SECRET', report)

    def test_output_limit_and_legacy_summary(self):
        self.assertIn('лимит вывода', test_report({'details': [{'error': 'Output limit exceeded (102400 bytes).'}]}, {}))
        self.assertEqual(test_report({'comment': '2 из 4'}, {}), '2 из 4')

    def test_callback_ids_accept_legacy_and_versioned_forms(self):
        for value in [12, '12', 'answer_12', versioned_callback_id(12, {'code': 'print(1)'})]:
            self.assertEqual(_parse_callback_id(value), 12)
        for value in ['12:bad', '12:' + 'z'*64, None]:
            self.assertIsNone(_parse_callback_id(value))

    def callback(self, old_value, new_value, finished=False):
        app = Flask(__name__)
        app.register_blueprint(callbacks_bp)
        answer = SimpleNamespace(id=1, question_id=2, attempt_id=3, value=new_value,
            check_state='pending', points=None, check_comment=None,
            attempt=SimpleNamespace(finished_at='finished' if finished else None),
            question=SimpleNamespace(max_points=12, check_type='docker', check_config={'tests': [{'name': 'Первый'}]}))
        query = Mock()
        query.filter_by.return_value.with_for_update.return_value.first.return_value = answer
        session, socketio = Mock(), Mock()
        with patch('routes.callbacks._verify_callback_auth', return_value=None), \
             patch('routes.callbacks._is_duplicate_callback', return_value=False), \
             patch('routes.callbacks._mark_callback_processed'), \
             patch('routes.callbacks.Answer', SimpleNamespace(query=query)), \
             patch('routes.callbacks.db', SimpleNamespace(session=session)), \
             patch.dict('sys.modules', {'manage': SimpleNamespace(socketio=socketio)}):
            response = app.test_client().post('/api/callback/check', json={
                'callback_id': versioned_callback_id(1, old_value), 'status': 'success',
                'points': 1, 'max_points': 4, 'details': [{'ok': True}]})
        return response, answer, socketio

    def test_old_code_cannot_change_active_or_finished_answer(self):
        for finished in [False, True]:
            response, answer, socket = self.callback({'code': 'old'}, {'code': 'new'}, finished)
            self.assertTrue(response.json['stale'])
            self.assertIsNone(answer.points)
            self.assertEqual(answer.check_state, 'pending')
            socket.emit.assert_not_called()

    def test_current_code_emits_version_and_report(self):
        value = {'code': 'print(1)', 'lang': 'python'}
        response, answer, socket = self.callback(value, value)
        self.assertEqual(response.status_code, 200)
        payload = socket.emit.call_args.args[1]
        self.assertEqual(payload['checked_value'], value)
        self.assertEqual(payload['points'], 3)
        self.assertIn('Первый: пройден', payload['check_comment'])
        self.assertIsNone(answer.points)


if __name__ == '__main__':
    unittest.main()
