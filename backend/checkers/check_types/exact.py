class ExactChecker:
    def check(self, answer_value, check_config, max_points):
        """
        Handles text_input (check_config.answer) and true_false_table (check_config.correct).
        Returns (points, comment).
        """
        if answer_value is None:
            return 0, 'Ответ не предоставлен'

        # multi_input: answers is a dict
        if 'answers' in check_config and isinstance(check_config['answers'], dict):
            correct = check_config['answers']
            given = answer_value if isinstance(answer_value, dict) else {}
            right = 0
            for key, expected in correct.items():
                got = str(given.get(key, '')).strip() if check_config.get('trim', True) else str(given.get(key, ''))
                exp = str(expected).strip() if check_config.get('trim', True) else str(expected)
                if not check_config.get('case_sensitive', False):
                    got, exp = got.lower(), exp.lower()
                if got == exp:
                    right += 1
            if check_config.get('partial_scoring', True):
                return round(max_points * right / len(correct)), f'{right} из {len(correct)} верно'
            return (max_points if right == len(correct) else 0), f'{right} из {len(correct)} верно'

        # true_false_table
        if 'correct' in check_config:
            correct = check_config['correct']
            given = answer_value.get('answers', [])
            if len(given) != len(correct):
                return 0, 'Неверное количество ответов'
            right = sum(1 for a, b in zip(given, correct) if a == b)
            if check_config.get('partial_scoring', True):
                points = round(max_points * right / len(correct))
                return points, f'{right} из {len(correct)} верно'
            else:
                return (max_points if right == len(correct) else 0), f'{right} из {len(correct)} верно'

        # text_input
        expected = str(check_config.get('answer', ''))
        given = str(answer_value.get('text', ''))

        if check_config.get('trim', True):
            expected = expected.strip()
            given = given.strip()

        if check_config.get('normalize_whitespace', False):
            import re
            expected = re.sub(r'\s+', ' ', expected)
            given = re.sub(r'\s+', ' ', given)

        if not check_config.get('case_sensitive', False):
            expected = expected.lower()
            given = given.lower()

        if given == expected:
            return max_points, 'Верно'
        return 0, f'Неверно. Ожидалось: {check_config.get("answer", "")}'
