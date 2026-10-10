"""Validate imported tests and answer drafts before they reach the checkers."""
from math import isfinite

from checkers.matrix import is_square, validate_matrix_question
from checkers.registry import CHECK_TYPES, VALID_QUESTION_TYPES


def _scalar(value):
    return value is None or isinstance(value, str) or type(value) is int or (type(value) is float and isfinite(value))


def validate_answer(value, question):
    # Empty and partially completed drafts are valid answers.
    if value is None:
        return
    kind = question.type
    if kind == 'interactive' and question.check_type not in ('ai', 'docker'):
        return
    if not isinstance(value, dict):
        raise ValueError('Ответ должен быть объектом JSON')
    if kind in ('text_input', 'code_input') or question.check_type in ('ai', 'docker'):
        for key in ('text', 'code', 'lang'):
            if key in value and not isinstance(value[key], str):
                raise ValueError(f'Поле {key} должно быть строкой')
    ui = question.ui_config or {}
    if kind == 'multi_input' and not all(_scalar(item) for item in value.values()):
        raise ValueError('Значения полей должны быть текстом или числами')
    if kind in ('true_false_table', 'choice_table'):
        given = value.get('answers', [])
        rows = ui.get('statements' if kind == 'true_false_table' else 'items', [])
        if not isinstance(given, list) or len(given) > len(rows):
            raise ValueError('Неверный формат таблицы ответов')
        for item in given:
            if item is None:
                continue
            if kind == 'true_false_table':
                valid = type(item) is bool
            else:
                valid = any(type(item) is type(option.get('value')) and item == option['value']
                            for option in ui.get('options', []))
            if not valid:
                raise ValueError('Недопустимое значение в таблице ответов')
    if kind == 'matrix_input':
        matrix = value.get('matrix')
        if matrix is not None and (not is_square(matrix, ui.get('size'))
                                   or any(not _scalar(cell) for row in matrix for cell in row)):
            raise ValueError('Неверный формат матрицы')
        fields = value.get('fields', {})
        if not isinstance(fields, dict) or not all(_scalar(item) for item in fields.values()):
            raise ValueError('Неверный формат дополнительных полей матрицы')


def validate_test_payload(data):
    if not isinstance(data, dict):
        raise ValueError('JSON должен содержать объект теста')
    title = data.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 255:
        raise ValueError('Название теста должно содержать от 1 до 255 символов')
    time_limit = data.get('time_limit')
    if time_limit is not None and (type(time_limit) is not int or time_limit <= 0):
        raise ValueError('Лимит времени должен быть положительным целым числом')
    variants = data.get('variants')
    if not isinstance(variants, list) or not variants:
        raise ValueError('Тест должен содержать хотя бы один вариант')
    totals = []
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError('Вариант должен быть объектом')
        questions = variant.get('questions')
        if not isinstance(questions, list) or not questions:
            raise ValueError('Каждый вариант должен содержать хотя бы один вопрос')
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError('Вопрос должен быть объектом')
            kind, check_type = question.get('type'), question.get('check_type')
            if not isinstance(kind, str) or kind not in VALID_QUESTION_TYPES:
                raise ValueError(f'Неизвестный тип вопроса: {kind}')
            if not isinstance(check_type, str) or check_type not in CHECK_TYPES:
                raise ValueError(f'Неизвестный тип проверки: {check_type}')
            title = question.get('title')
            if not isinstance(title, str) or not title.strip() or len(title) > 255:
                raise ValueError('Название вопроса должно содержать от 1 до 255 символов')
            points = question.get('max_points')
            if type(points) is not int or points < 0:
                raise ValueError('Максимальный балл должен быть неотрицательным целым числом')
            for key in ('check_config', 'ui_config'):
                if question.get(key) is not None and not isinstance(question[key], dict):
                    raise ValueError(f'{key} должен быть объектом')
            if 'allow_intermediate_check' in question and type(question['allow_intermediate_check']) is not bool:
                raise ValueError('allow_intermediate_check должен быть логическим значением')
            cfg = question.get('check_config') or {}
            if check_type == 'exact':
                if kind == 'multi_input' and (not isinstance(cfg.get('answers'), dict) or not cfg['answers']):
                    raise ValueError('multi_input: требуется непустой объект answers с эталонами')
                if kind in ('true_false_table', 'choice_table') and (
                    not isinstance(cfg.get('correct'), list) or not cfg['correct']
                ):
                    raise ValueError('Таблица должна содержать непустой список correct с эталонами')
            validate_matrix_question(question)
        totals.append(sum(question['max_points'] for question in questions))
    if len(set(totals)) != 1:
        raise ValueError('Сумма баллов должна быть одинакова во всех вариантах')
