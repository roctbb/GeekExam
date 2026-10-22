import json
from flask import Blueprint, jsonify, request, abort
from models import db
from auth import api_login_required, teacher_required, current_user_id
from attempt_lifecycle import lock_answer, finish_if_expired
from validation import validate_answer
from answer_limits import REQUEST_LIMIT, validate_answer_size

answers_bp = Blueprint('answers', __name__)


def _locked_answer(answer_id):
    answer, attempt = lock_answer(answer_id)
    if answer is None or attempt is None:
        abort(404)
    return answer, attempt


def _strip_nul_chars(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul_chars(item) for item in value]
    if isinstance(value, dict):
        return {
            _strip_nul_chars(key) if isinstance(key, str) else key: _strip_nul_chars(item)
            for key, item in value.items()
        }
    return value


@answers_bp.route('/api/answers/<int:answer_id>', methods=['PUT'])
@api_login_required
def save_answer(answer_id):
    if not request.is_json:
        return jsonify({'error': 'Требуется JSON с полем value'}), 422
    raw = request.stream.read(REQUEST_LIMIT + 1)
    if len(raw) > REQUEST_LIMIT:
        return jsonify({'error': 'Ответ слишком большой', 'error_code': 'answer_too_large'}), 413
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return jsonify({'error': 'Некорректный JSON ответа'}), 422
    answer, attempt = _locked_answer(answer_id)
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if attempt.finished_at or finish_if_expired(attempt):
        return jsonify({'error': 'Тест уже завершён', 'error_code': 'attempt_finished'}), 422

    if not isinstance(data, dict) or 'value' not in data:
        return jsonify({'error': 'Требуется объект с полем value'}), 422
    try:
        validate_answer_size(data['value'], answer.question)
        new_value = _strip_nul_chars(data['value'])
        validate_answer(new_value, answer.question)
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    # If value changed after an intermediate check, reset check state so the
    # answer is re-evaluated on final submission.
    if answer.value != new_value:
        answer.check_state = 'pending'
        answer.points = None
        answer.check_comment = None
    answer.value = new_value
    db.session.commit()
    return jsonify({'status': 'saved'})


@answers_bp.route('/api/answers/<int:answer_id>/check', methods=['POST'])
@api_login_required
def intermediate_check(answer_id):
    answer, attempt = _locked_answer(answer_id)
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if attempt.finished_at or finish_if_expired(attempt):
        return jsonify({'error': 'Тест уже завершён', 'error_code': 'attempt_finished'}), 422
    if not answer.question.allow_intermediate_check:
        return jsonify({'error': 'Промежуточная проверка недоступна'}), 422
    if answer.question.check_type == 'manual':
        return jsonify({'error': 'Промежуточная проверка недоступна для ручной проверки'}), 422

    if answer.check_state != 'pending':
        return jsonify({'error': 'Проверка уже выполняется'}), 422
    answer.check_state = 'checking'
    db.session.commit()

    from celery_tasks.check_answer import check_single_answer
    check_single_answer.delay(answer_id, intermediate=True)

    return jsonify({'status': 'checking'})


@answers_bp.route('/api/answers/<int:answer_id>/recheck', methods=['POST'])
@teacher_required
def recheck_answer(answer_id):
    """Teacher-triggered re-check for async check types (ai, docker)."""
    answer, attempt = _locked_answer(answer_id)
    if not attempt.finished_at:
        return jsonify({'error': 'Перепроверка доступна только для завершённых работ'}), 422
    question = answer.question
    from checkers.registry import is_async_check
    if not is_async_check(question.check_type):
        return jsonify({'error': 'Перепроверка доступна только для ai/docker вопросов'}), 422

    if answer.check_state == 'checking':
        return jsonify({'error': 'Проверка уже выполняется'}), 422
    answer.check_state = 'checking'
    answer.points = None
    answer.check_comment = None
    attempt.is_checked = False
    attempt.total_points = None
    db.session.commit()

    from celery_tasks.check_answer import check_single_answer
    check_single_answer.delay(answer_id, intermediate=False)

    return jsonify({'status': 'checking'})


@answers_bp.route('/api/answers/<int:answer_id>/grade', methods=['PUT'])
@teacher_required
def grade_answer(answer_id):
    answer, attempt = _locked_answer(answer_id)
    if not attempt.finished_at:
        return jsonify({'error': 'Оценивание доступно только для завершённых работ'}), 422
    if answer.check_state == 'checking':
        return jsonify({'error': 'Дождитесь завершения автоматической проверки'}), 422
    data = request.get_json()
    points = data.get('points') if isinstance(data, dict) else None
    if type(points) is not int or not 0 <= points <= answer.question.max_points:
        return jsonify({'error': f'Укажите целое число баллов от 0 до {answer.question.max_points}'}), 422
    comment = data.get('comment')
    if comment is not None and not isinstance(comment, str):
        return jsonify({'error': 'Комментарий должен быть строкой'}), 422
    answer.points = points
    answer.check_comment = _strip_nul_chars(comment)
    answer.check_state = 'checked'
    db.session.commit()

    # Check if all answers in attempt are now checked.
    # Use _inner variant — we're already inside a Flask request context.
    from celery_tasks.check_answer import _finalize_attempt_if_done_inner
    _finalize_attempt_if_done_inner(answer.attempt_id, force_recalculate=True)

    return jsonify({'status': 'graded'})
