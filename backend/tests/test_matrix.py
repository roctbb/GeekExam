import copy
import unittest

from checkers.check_types.exact import ExactChecker
from checkers.matrix import validate_matrix_question


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.question = {
            'type': 'matrix_input', 'check_type': 'exact',
            'ui_config': {'size': 3, 'fields': [{'name': 'corner'}, {'name': 'center'}]},
            'check_config': {'matrix': [[0, 2, 3], [4, 5, 6], [7, 8, 9]],
                             'fields': {'corner': '30', 'center': '390'}, 'scoring': 'rows'},
        }
        self.answer = {'matrix': [['0', '2', '3'], ['4', '5', '6'], ['7', '8', '9']],
                       'fields': {'corner': '30', 'center': '390'}}

    def score(self, answer, cfg=None, points=5):
        return ExactChecker().check(answer, cfg or self.question['check_config'], points)[0]

    def test_rows_and_intermediate_fields_are_independent(self):
        validate_matrix_question(self.question)
        self.assertEqual(self.score(self.answer), 5)
        self.answer['matrix'][0][0] = 'wrong'
        self.assertEqual(self.score(self.answer), 4)
        self.answer['matrix'][0][1] = 'wrong'
        self.assertEqual(self.score(self.answer), 4)
        self.answer['fields']['corner'] = ''
        self.assertEqual(self.score(self.answer), 3)

    def test_all_scoring_units_combinations(self):
        for mask in range(32):
            answer = copy.deepcopy(self.answer)
            for r in range(3):
                if not mask & (1 << r):
                    answer['matrix'][r][0] = ''
            for i, name in enumerate(['corner', 'center'], start=3):
                if not mask & (1 << i):
                    answer['fields'][name] = ''
            self.assertEqual(self.score(answer), mask.bit_count())

    def test_arbitrary_sizes_cells_and_all_or_nothing(self):
        for n in [1, 2, 4, 10]:
            matrix = [[str(r * n + c) for c in range(n)] for r in range(n)]
            cfg = {'matrix': matrix, 'scoring': 'cells'}
            answer = {'matrix': copy.deepcopy(matrix)}
            self.assertEqual(self.score(answer, cfg, n*n), n*n)
            answer['matrix'][0][0] = 'bad'
            self.assertEqual(self.score(answer, cfg, n*n), n*n-1)
            cfg['scoring'] = 'all'
            self.assertEqual(self.score(answer, cfg), 0)

    def test_missing_or_wrong_shape_does_not_crash(self):
        for value in [None, '', [], {}, {'matrix': []}, {'matrix': [[0]]}, {'matrix': [None]*3}]:
            self.assertEqual(self.score(value), 0)

    def test_whitespace_and_zero(self):
        self.answer['matrix'][0][0] = ' \u202c0 '
        self.assertEqual(self.score(self.answer), 5)

    def test_bad_imports_are_rejected(self):
        for size in [0, -1, 51, '3', True]:
            q = copy.deepcopy(self.question)
            q['ui_config']['size'] = size
            with self.assertRaises(ValueError):
                validate_matrix_question(q)
        for patch in [{'matrix': [[1]]}, {'scoring': 'unknown'}, {'fields': {}}, {'field_weights': {'corner': -1}}]:
            q = copy.deepcopy(self.question)
            q['check_config'].update(patch)
            with self.assertRaises(ValueError):
                validate_matrix_question(q)

    def test_legacy_answers_still_work(self):
        self.assertEqual(ExactChecker().check({'row1': '0  1 2'}, {'answers': {'row1': '0 1 2'}, 'normalize_whitespace': True}, 1)[0], 1)


if __name__ == '__main__':
    unittest.main()
