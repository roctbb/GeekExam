from flask import Blueprint, jsonify, request
from models import db, Answer, Attempt
from auth import api_login_required, teacher_required, current_user_id

answers_bp = Blueprint('answers', __name__)


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
    answer = Answer.query.get_or_404(answer_id)
    attempt = answer.attempt
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if attempt.finished_at:
        return jsonify({'error': 'Тест уже завершён'}), 422

    data = request.get_json()
    new_value = _strip_nul_chars(data.get('value'))
    # If value changed after an intermediate check, reset check state so the
    # answer is re-evaluated on final submission.
    if answer.value != new_value and answer.question.check_type != 'manual':
        answer.check_state = 'pending'
        answer.points = None
        answer.check_comment = None
    answer.value = new_value
    db.session.commit()
    return jsonify({'status': 'saved'})


@answers_bp.route('/api/answers/<int:answer_id>/check', methods=['POST'])
@api_login_required
def intermediate_check(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    attempt = answer.attempt
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if attempt.finished_at:
        return jsonify({'error': 'Тест уже завершён'}), 422
    if not answer.question.allow_intermediate_check:
        return jsonify({'error': 'Промежуточная проверка недоступна'}), 422
    if answer.question.check_type == 'manual':
        return jsonify({'error': 'Промежуточная проверка недоступна для ручной проверки'}), 422

    # Atomic compare-and-swap: only transition pending→checking, never checking→checking.
    # This prevents a double-click / network-retry from dispatching two concurrent tasks.
    updated = (
        db.session.execute(
            db.update(Answer)
            .where(Answer.id == answer_id, Answer.check_state == 'pending')
            .values(check_state='checking')
        ).rowcount
    )
    db.session.commit()
    if updated == 0:
        return jsonify({'error': 'Проверка уже выполняется'}), 422

    from celery_tasks.check_answer import check_single_answer
    check_single_answer.delay(answer_id, intermediate=True)

    return jsonify({'status': 'checking'})


@answers_bp.route('/api/answers/<int:answer_id>/recheck', methods=['POST'])
@teacher_required
def recheck_answer(answer_id):
    """Teacher-triggered re-check for async check types (ai, docker)."""
    answer = Answer.query.get_or_404(answer_id)
    question = answer.question
    from checkers.registry import is_async_check
    if not is_async_check(question.check_type):
        return jsonify({'error': 'Перепроверка доступна только для ai/docker вопросов'}), 422

    # Atomic transition: only allow if not already checking.
    updated = (
        db.session.execute(
            db.update(Answer)
            .where(Answer.id == answer_id, Answer.check_state != 'checking')
            .values(check_state='checking')
        ).rowcount
    )
    db.session.commit()
    if updated == 0:
        return jsonify({'error': 'Проверка уже выполняется'}), 422

    from celery_tasks.check_answer import check_single_answer
    check_single_answer.delay(answer_id, intermediate=False)

    return jsonify({'status': 'checking'})


@answers_bp.route('/api/answers/<int:answer_id>/grade', methods=['PUT'])
@teacher_required
def grade_answer(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    data = request.get_json()
    answer.points = data.get('points')
    answer.check_comment = _strip_nul_chars(data.get('comment'))
    answer.check_state = 'checked'
    db.session.commit()

    # Check if all answers in attempt are now checked.
    # Use _inner variant — we're already inside a Flask request context.
    from celery_tasks.check_answer import _finalize_attempt_if_done_inner
    _finalize_attempt_if_done_inner(answer.attempt_id, force_recalculate=True)

    return jsonify({'status': 'graded'})
