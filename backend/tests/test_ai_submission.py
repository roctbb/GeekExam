import unittest
from unittest.mock import Mock, patch

from checkers.check_types.docker import DockerChecker


class AiSubmissionTests(unittest.TestCase):
    def submit(self, check_type='ai', config=None):
        config = config if config is not None else {'prompt': 'Критерии'}
        with patch('checkers.check_types.docker.requests.post',
                   return_value=Mock(status_code=200)) as post, \
             patch('checkers.check_types.docker._make_service_token', return_value='test'):
            result = DockerChecker().submit(
                1, {'text': 'Пояснение\nкод'}, config, 'Условие', check_type, 3)
        self.assertEqual(result, (True, None))
        return post.call_args.kwargs['json']

    def test_ai_requests_use_rubric_and_keep_multiline_answer(self):
        config = {'prompt': 'Критерии'}
        payload = self.submit(config=config)
        self.assertEqual(payload['check_config'], {
            'prompt': 'Критерии', 'max_points': 3, 'assessment_mode': 'rubric'})
        self.assertEqual(payload['code'], 'Пояснение\nкод')
        self.assertEqual(config, {'prompt': 'Критерии'})

    def test_explicit_code_mode_is_preserved(self):
        self.assertEqual(self.submit(config={'assessment_mode': 'code'})
                         ['check_config']['assessment_mode'], 'code')

    def test_docker_checks_keep_their_configuration(self):
        payload = self.submit(check_type='docker', config={'tests': []})
        self.assertEqual(payload['check_type'], 'tests')
        self.assertEqual(payload['check_config'], {'tests': []})


if __name__ == '__main__':
    unittest.main()
