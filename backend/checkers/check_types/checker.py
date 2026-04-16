class PythonChecker:
    def check(self, answer_value, check_config, max_points):
        """
        Executes teacher-provided Python checker_code.
        The code must define check(answer_value, max_points) -> (points, comment).
        """
        checker_code = check_config.get('checker_code', '')
        if not checker_code:
            return 0, 'Checker не настроен'
        try:
            namespace = {}
            exec(checker_code, namespace)
            check_fn = namespace.get('check')
            if not check_fn:
                return 0, 'Функция check не найдена в checker_code'
            result = check_fn(answer_value, max_points)
            return result[0], result[1]
        except Exception as e:
            return 0, f'Ошибка проверки: {e}'
