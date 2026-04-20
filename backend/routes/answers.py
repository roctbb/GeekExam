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
    answer.value = _strip_nul_chars(data.get('value'))
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
    if answer.check_state == 'checking':
        return jsonify({'error': 'Проверка уже выполняется'}), 422

    answer.check_state = 'checking'
    db.session.commit()

    from celery_tasks.check_answer import check_single_answer
    check_single_answer.delay(answer_id, intermediate=True)

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

    # Check if all answers in attempt are now checked
    from celery_tasks.check_answer import _finalize_attempt_if_done
    _finalize_attempt_if_done(answer.attempt_id, force_recalculate=True)

    return jsonify({'status': 'graded'})
