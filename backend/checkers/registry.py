from checkers.check_types.exact import ExactChecker
from checkers.check_types.checker import PythonChecker
from checkers.check_types.docker import DockerChecker

CHECK_TYPES = {
    'exact': ExactChecker,
    'checker': PythonChecker,
    'docker': DockerChecker,
    'ai': DockerChecker,  # AI also goes through GeekPasteV2
    'manual': None,       # No auto-check
}

VALID_QUESTION_TYPES = {'text_input', 'code_input', 'true_false_table', 'interactive', 'multi_input'}


def get_checker(check_type):
    cls = CHECK_TYPES.get(check_type)
    if cls is None:
        return None
    return cls()


def is_async_check(check_type):
    return check_type in ('docker', 'ai')
