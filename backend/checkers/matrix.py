"""Validation and exact grading for square matrix answers."""
from math import isfinite


def is_square(value, size):
    return (isinstance(value, list) and len(value) == size
            and all(isinstance(row, list) and len(row) == size for row in value))


def validate_matrix_question(question):
    if question.get('type') != 'matrix_input':
        return
    ui = question.get('ui_config') or {}
    if not isinstance(ui, dict):
        raise ValueError('matrix_input: ui_config должен быть объектом')
    size = ui.get('size')
    if type(size) is not int or not 1 <= size <= 50:
        raise ValueError('matrix_input: size должен быть целым числом от 1 до 50')
    fields = ui.get('fields', [])
    if not isinstance(fields, list) or any(not isinstance(f, dict) or not isinstance(f.get('name'), str) or not f['name'] for f in fields):
        raise ValueError('matrix_input: fields должен содержать именованные поля')
    names = [f['name'] for f in fields]
    if len(set(names)) != len(names):
        raise ValueError('matrix_input: имена полей должны быть уникальны')
    if question.get('check_type') != 'exact':
        return
    cfg = question.get('check_config') or {}
    if not isinstance(cfg, dict):
        raise ValueError('matrix_input: check_config должен быть объектом')
    expected = cfg.get('matrix')
    if not is_square(expected, size) or any(isinstance(x, (list, dict, bool)) or x is None or not str(x).strip() for row in expected for x in row):
        raise ValueError('matrix_input: эталон matrix должен быть заполненной матрицей size × size')
    if cfg.get('scoring', 'rows') not in ('rows', 'cells', 'all'):
        raise ValueError('matrix_input: scoring должен быть rows, cells или all')
    expected_fields = cfg.get('fields', {})
    if not isinstance(expected_fields, dict) or set(expected_fields) != set(names):
        raise ValueError('matrix_input: эталоны fields должны совпадать с полями ui_config')
    weights = cfg.get('field_weights', {})
    if not isinstance(weights, dict) or not set(weights).issubset(names):
        raise ValueError('matrix_input: неизвестные имена в field_weights')
    if any(type(w) not in (int, float) or not isfinite(w) or w <= 0 for w in weights.values()):
        raise ValueError('matrix_input: веса полей должны быть положительными числами')


def check_matrix(answer, cfg, max_points, normalize):
    expected = cfg['matrix']
    size = len(expected)
    given = answer.get('matrix') if isinstance(answer, dict) else None
    if not is_square(given, size):
        return 0, 'Неверный размер матрицы'
    cells = [[not isinstance(given[r][c], (list, dict, bool))
              and given[r][c] is not None
              and normalize(given[r][c], cfg) == normalize(expected[r][c], cfg)
              for c in range(size)] for r in range(size)]
    mode = cfg.get('scoring', 'rows')
    units = ([all(row) for row in cells] if mode == 'rows' else
             [cell for row in cells for cell in row] if mode == 'cells' else
             [all(all(row) for row in cells)])
    right, total = sum(units), len(units)
    given_fields = answer.get('fields', {})
    if not isinstance(given_fields, dict):
        given_fields = {}
    for key, value in cfg.get('fields', {}).items():
        weight = cfg.get('field_weights', {}).get(key, 1)
        total += weight
        if normalize(given_fields.get(key, ''), cfg) == normalize(value, cfg):
            right += weight
    points = round(max_points * right / total) if cfg.get('partial_scoring', True) else (max_points if right == total else 0)
    return points, f'Получено {points} из {max_points} баллов'
