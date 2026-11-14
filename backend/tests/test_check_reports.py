import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from checkers.check_report import test_report as build_test_report


class CheckReportTests(unittest.TestCase):
    def test_detailed_report_and_hidden_test_data(self):
        report = build_test_report({'comment': '1 из 5 тестов пройдено', 'details': [
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
        self.assertIn('лимит вывода', build_test_report({'details': [{'error': 'Output limit exceeded (102400 bytes).'}]}, {}))
        self.assertEqual(build_test_report({'comment': '2 из 4'}, {}), '2 из 4')
