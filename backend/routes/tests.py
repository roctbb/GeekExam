from time_utils import utc_iso
import json
from datetime import datetime
from flask import Blueprint, jsonify, request
from models import db, Test, Variant, Question, Attempt
from auth import teacher_required, current_user_id
from validation import validate_test_payload
from attempt_lifecycle import mark_locked_attempt_finished, publish_attempt_finished

tests_bp = Blueprint('tests', __name__)


def _time_limit_conflict(test, data):
    if 'expected_time_limit' in data and data['expected_time_limit'] != test.time_limit:
        return jsonify({'error': 'Лимит времени уже изменён. Обновите страницу перед сохранением.',
                        'time_limit': test.time_limit}), 409
    return None


def _sync_source_params(test):
    try:
        payload = json.loads(test.source_json) if test.source_json else None
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict) or not payload:
        payload = _current_test_payload(test)
    payload.update(title=test.title, description=test.description, time_limit=test.time_limit)
    test.source_json = json.dumps(payload, ensure_ascii=False)


def _parse_and_create_test(data, test=None):
    """Parse JSON dict and populate Test/Variant/Question objects."""
    validate_test_payload(data)

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


def _update_existing_test_payload(data, test):
    validate_test_payload(data)
    variants_data = data.get('variants', [])
    variants = list(test.variants)
    if len(variants_data) != len(variants):
        raise ValueError('После начала прохождения нельзя добавлять или удалять варианты')

    for variant, vdata in zip(variants, variants_data):
        questions_data = vdata.get('questions', [])
        questions = list(variant.questions)
        if len(questions_data) != len(questions):
            raise ValueError('После начала прохождения нельзя добавлять или удалять вопросы')

        variant.title = vdata.get('title', variant.title)
        for question, qdata in zip(questions, questions_data):
            question.type = qdata['type']
            question.title = qdata['title']
            question.body = qdata.get('body')
            question.max_points = qdata['max_points']
            question.check_type = qdata['check_type']
            question.check_config = qdata.get('check_config')
            question.ui_config = qdata.get('ui_config')
            question.allow_intermediate_check = qdata.get('allow_intermediate_check', False)

    test.title = data['title']
    test.description = data.get('description')
    test.time_limit = data.get('time_limit')
    test.source_json = json.dumps(data, ensure_ascii=False)

    for attempt in test.attempts:
        attempt.max_points = sum(q.max_points for q in attempt.variant.questions)

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
        'created_at': utc_iso(test.created_at),
        'variant_count': len(test.variants),
        'attempt_count': len(test.attempts),
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
    if data is None:
        return jsonify({'error': 'JSON required'}), 400
    try:
        test = _parse_and_create_test(data)
        db.session.add(test)
        db.session.commit()
        return jsonify(_test_to_dict(test)), 201
    except (ValueError, KeyError) as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 422


@tests_bp.route('/api/tests/<int:test_id>', methods=['GET'])
@teacher_required
def get_test(test_id):
    test = Test.query.get_or_404(test_id)
    return jsonify(_test_to_dict(test, include_variants=True))


@tests_bp.route('/api/tests/<int:test_id>', methods=['PUT'])
@teacher_required
def update_test(test_id):
    test = Test.query.filter_by(id=test_id).with_for_update().first_or_404()
    data = request.get_json()
    if data is None:
        return jsonify({'error': 'JSON required'}), 400

    conflict = _time_limit_conflict(test, data)
    if conflict:
        return conflict

    has_attempts = Attempt.query.filter_by(test_id=test.id).first() is not None
    try:
        if has_attempts:
            _update_existing_test_payload(data, test)
        else:
            _parse_and_create_test(data, test=test)
        db.session.commit()
        return jsonify(_test_to_dict(test))
    except (ValueError, KeyError) as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 422


@tests_bp.route('/api/tests/<int:test_id>/params', methods=['PUT'])
@teacher_required
def update_test_params(test_id):
    test = Test.query.filter_by(id=test_id).with_for_update().first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON required'}), 400
    conflict = _time_limit_conflict(test, data)
    if conflict:
        return conflict

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Название теста не может быть пустым'}), 422

    time_limit = data.get('time_limit')
    if time_limit is not None:
        if type(time_limit) is not int or time_limit <= 0:
            return jsonify({'error': 'Лимит времени должен быть положительным целым числом'}), 422

    test.title = title
    test.description = data.get('description')
    test.time_limit = time_limit

    _sync_source_params(test)

    db.session.commit()
    return jsonify(_test_to_dict(test))


@tests_bp.route('/api/tests/<int:test_id>/extend-time', methods=['POST'])
@teacher_required
def extend_test_time(test_id):
    test = Test.query.filter_by(id=test_id).with_for_update().first_or_404()
    data = request.get_json()
    if not isinstance(data, dict) or type(data.get('minutes')) is not int or data['minutes'] <= 0:
        return jsonify({'error': 'Укажите положительное целое число дополнительных минут'}), 422
    if 'expected_time_limit' not in data:
        return jsonify({'error': 'Обновите страницу перед продлением времени'}), 422
    conflict = _time_limit_conflict(test, data)
    if conflict:
        return conflict
    if test.time_limit is None:
        return jsonify({'error': 'У теста нет ограничения времени'}), 422
    test.time_limit += data['minutes']
    _sync_source_params(test)
    db.session.commit()
    from manage import socketio
    for (attempt_id,) in db.session.query(Attempt.id).filter_by(test_id=test_id, finished_at=None).all():
        socketio.emit('time_limit_updated', {'test_id': test_id}, room=f'attempt_{attempt_id}')
    return jsonify(_test_to_dict(test))


@tests_bp.route('/api/tests/<int:test_id>', methods=['DELETE'])
@teacher_required
def delete_test(test_id):
    test = Test.query.get_or_404(test_id)
    for attempt in list(test.attempts):
        db.session.delete(attempt)
    db.session.flush()
    db.session.delete(test)
    db.session.commit()
    return '', 204


@tests_bp.route('/api/tests/<int:test_id>/activate', methods=['POST'])
@teacher_required
def activate_test(test_id):
    test = Test.query.get_or_404(test_id)
    if not test.code:
        return jsonify({'error': 'Установите код теста перед запуском'}), 422
    try:
        validate_test_payload(_current_test_payload(test))
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    test.is_active = True
    db.session.commit()
    return jsonify({'is_active': True})


@tests_bp.route('/api/tests/<int:test_id>/deactivate', methods=['POST'])
@teacher_required
def deactivate_test(test_id):
    test = Test.query.filter_by(id=test_id).with_for_update().first_or_404()
    test.is_active = False
    attempts = Attempt.query.filter_by(test_id=test_id, finished_at=None).order_by(Attempt.id).with_for_update().all()
    now = datetime.utcnow()
    finished = []
    for attempt in attempts:
        if mark_locked_attempt_finished(attempt, now):
            finished.append((attempt.id, attempt.finished_at))
    db.session.commit()
    for attempt_id, finished_at in finished:
        publish_attempt_finished(attempt_id, finished_at)
    return jsonify({'is_active': False, 'finished_attempts': len(finished)})


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
            'started_at': utc_iso(a.started_at),
            'finished_at': utc_iso(a.finished_at),
            'is_checked': a.is_checked,
            'total_points': a.total_points,
            'max_points': a.max_points,
        }
        for a in attempts
    ])
