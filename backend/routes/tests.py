import json
from flask import Blueprint, jsonify, request
from models import db, Test, Variant, Question, Attempt
from auth import teacher_required, current_user_id
from checkers.registry import VALID_QUESTION_TYPES, CHECK_TYPES

tests_bp = Blueprint('tests', __name__)


def _parse_and_create_test(data, test=None):
    """Parse JSON dict and populate Test/Variant/Question objects."""
    total_per_variant = None
    for v in data.get('variants', []):
        s = sum(q.get('max_points', 0) for q in v.get('questions', []))
        if total_per_variant is None:
            total_per_variant = s
        elif s != total_per_variant:
            raise ValueError('Сумма баллов должна быть одинакова во всех вариантах')

    for v in data.get('variants', []):
        for q in v.get('questions', []):
            if q.get('type') not in VALID_QUESTION_TYPES:
                raise ValueError(f'Неизвестный тип вопроса: {q.get("type")}')
            if q.get('check_type') not in CHECK_TYPES:
                raise ValueError(f'Неизвестный тип проверки: {q.get("check_type")}')

    if test is None:
        test = Test(created_by=current_user_id())
    else:
        # Remove old variants
        for v in list(test.variants):
            db.session.delete(v)
        db.session.flush()

    test.title = data['title']
    test.description = data.get('description')
    test.time_limit = data.get('time_limit')
    test.source_json = json.dumps(data, ensure_ascii=False)

    for i, vdata in enumerate(data.get('variants', [])):
        variant = Variant(title=vdata.get('title', f'Вариант {i+1}'), order=i)
        test.variants.append(variant)
        for j, qdata in enumerate(vdata.get('questions', [])):
            question = Question(
                order=j,
                type=qdata['type'],
                title=qdata['title'],
                body=qdata.get('body'),
                max_points=qdata['max_points'],
                check_type=qdata['check_type'],
                check_config=qdata.get('check_config'),
                ui_config=qdata.get('ui_config'),
                allow_intermediate_check=qdata.get('allow_intermediate_check', False),
            )
            variant.questions.append(question)

    return test


def _current_test_payload(test):
    return {
        'title': test.title,
        'description': test.description,
        'time_limit': test.time_limit,
        'variants': [
            {
                'title': v.title,
                'questions': [
                    {
                        'type': q.type,
                        'title': q.title,
                        'body': q.body,
                        'max_points': q.max_points,
                        'check_type': q.check_type,
                        'check_config': q.check_config,
                        'ui_config': q.ui_config,
                        'allow_intermediate_check': q.allow_intermediate_check,
                    }
                    for q in v.questions
                ],
            }
            for v in test.variants
        ],
    }


def _test_to_dict(test, include_variants=False):
    d = {
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'code': test.code,
        'time_limit': test.time_limit,
        'is_active': test.is_active,
        'created_by': test.created_by,
        'created_at': test.created_at.isoformat() if test.created_at else None,
    }
    if include_variants:
        source_json = None
        if test.source_json:
            try:
                source_json = json.loads(test.source_json)
            except json.JSONDecodeError:
                source_json = None

        d['source_json'] = source_json
        d['variants'] = [
            {
                'id': v.id,
                'title': v.title,
                'questions': [
                    {
                        'id': q.id,
                        'order': q.order,
                        'type': q.type,
                        'title': q.title,
                        'body': q.body,
                        'max_points': q.max_points,
                        'check_type': q.check_type,
                        'check_config': q.check_config,
                        'ui_config': q.ui_config,
                        'allow_intermediate_check': q.allow_intermediate_check,
                    }
                    for q in v.questions
                ],
            }
            for v in test.variants
        ]
    return d


@tests_bp.route('/api/tests', methods=['GET'])
@teacher_required
def list_tests():
    tests = Test.query.order_by(Test.created_at.desc()).all()
    return jsonify([_test_to_dict(t) for t in tests])


@tests_bp.route('/api/tests', methods=['POST'])
@teacher_required
def create_test():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON required'}), 400
    try:
        test = _parse_and_create_test(data)
        db.session.add(test)
        db.session.commit()
        return jsonify(_test_to_dict(test)), 201
    except (ValueError, KeyError) as e:
        return jsonify({'error': str(e)}), 422


@tests_bp.route('/api/tests/<int:test_id>', methods=['GET'])
@teacher_required
def get_test(test_id):
    test = Test.query.get_or_404(test_id)
    return jsonify(_test_to_dict(test, include_variants=True))


@tests_bp.route('/api/tests/<int:test_id>', methods=['PUT'])
@teacher_required
def update_test(test_id):
    test = Test.query.get_or_404(test_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON required'}), 400

    has_attempts = Attempt.query.filter_by(test_id=test.id).first() is not None
    if has_attempts:
        return jsonify({'error': 'Нельзя изменять варианты и вопросы после начала прохождения теста'}), 422

    try:
        _parse_and_create_test(data, test=test)
        db.session.commit()
        return jsonify(_test_to_dict(test))
    except (ValueError, KeyError) as e:
        return jsonify({'error': str(e)}), 422


@tests_bp.route('/api/tests/<int:test_id>/params', methods=['PUT'])
@teacher_required
def update_test_params(test_id):
    test = Test.query.get_or_404(test_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON required'}), 400

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Название теста не может быть пустым'}), 422

    time_limit = data.get('time_limit')
    if time_limit is not None:
        if not isinstance(time_limit, int) or time_limit <= 0:
            return jsonify({'error': 'Лимит времени должен быть положительным целым числом'}), 422

    test.title = title
    test.description = data.get('description')
    test.time_limit = time_limit

    # Keep source_json in sync so the editor always receives актуальные параметры.
    source_payload = None
    if test.source_json:
        try:
            source_payload = json.loads(test.source_json)
        except json.JSONDecodeError:
            source_payload = None
    if not source_payload:
        source_payload = _current_test_payload(test)

    source_payload['title'] = test.title
    source_payload['description'] = test.description
    source_payload['time_limit'] = test.time_limit
    test.source_json = json.dumps(source_payload, ensure_ascii=False)

    db.session.commit()
    return jsonify(_test_to_dict(test))


@tests_bp.route('/api/tests/<int:test_id>', methods=['DELETE'])
@teacher_required
def delete_test(test_id):
    test = Test.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    return '', 204


@tests_bp.route('/api/tests/<int:test_id>/activate', methods=['POST'])
@teacher_required
def activate_test(test_id):
    test = Test.query.get_or_404(test_id)
    if not test.code:
        return jsonify({'error': 'Установите код теста перед запуском'}), 422
    test.is_active = True
    db.session.commit()
    return jsonify({'is_active': True})


@tests_bp.route('/api/tests/<int:test_id>/deactivate', methods=['POST'])
@teacher_required
def deactivate_test(test_id):
    test = Test.query.get_or_404(test_id)
    test.is_active = False
    db.session.commit()
    return jsonify({'is_active': False})


@tests_bp.route('/api/tests/<int:test_id>/code', methods=['PUT'])
@teacher_required
def set_test_code(test_id):
    test = Test.query.get_or_404(test_id)
    data = request.get_json()
    code = data.get('code', '').strip().upper()
    if not code:
        return jsonify({'error': 'Код не может быть пустым'}), 422
    existing = Test.query.filter(Test.code == code, Test.id != test_id).first()
    if existing:
        return jsonify({'error': 'Этот код уже используется'}), 422
    test.code = code
    db.session.commit()
    return jsonify({'code': test.code})


@tests_bp.route('/api/tests/<int:test_id>/attempts', methods=['GET'])
@teacher_required
def test_attempts(test_id):
    attempts = Attempt.query.filter_by(test_id=test_id).all()
    return jsonify([
        {
            'id': a.id,
            'user_id': a.user_id,
            'user_name': a.user.name,
            'variant_id': a.variant_id,
            'variant_title': a.variant.title,
            'started_at': a.started_at.isoformat() if a.started_at else None,
            'finished_at': a.finished_at.isoformat() if a.finished_at else None,
            'is_checked': a.is_checked,
            'total_points': a.total_points,
            'max_points': a.max_points,
        }
        for a in attempts
    ])
