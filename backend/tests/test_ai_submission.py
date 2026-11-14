import unittest
from unittest.mock import patch
from checkers.check_types.docker import DockerChecker

class AiSubmissionTests(unittest.TestCase):
    def test_ai_and_docker_use_only_executor_and_preserve_request(self):
        for check_type in ('ai','docker'):
            answer={'text':'Пояснение\nкод'};config={'prompt':'Критерии'}
            with self.subTest(check_type=check_type), patch('executor_service.submit',return_value=(True,None)) as submit:
                self.assertEqual(DockerChecker().submit(1,answer,config,'Условие',check_type,3),(True,None))
                submit.assert_called_once_with(1,answer,config,'Условие',check_type,3)
            self.assertEqual(config,{'prompt':'Критерии'})
