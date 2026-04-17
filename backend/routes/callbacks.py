from flask import Blueprint, jsonify, request
from models import db, Answer

callbacks_bp = Blueprint('callbacks', __name__)


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


@callbacks_bp.route('/api/callback/check', methods=['POST'])
def check_callback():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    answer_id = data.get('callback_id')
    if not answer_id:
        return jsonify({'error': 'Missing callback_id'}), 400

    answer = Answer.query.get(int(answer_id))
    if not answer:
        return jsonify({'error': 'Answer not found'}), 404

    if data.get('status') == 'success':
        max_pts = answer.question.max_points
        paste_max = data.get('max_points', 1) or 1
        paste_pts = data.get('points', 0) or 0
        answer.points = round(max_pts * paste_pts / paste_max)
        answer.check_state = 'checked'
    else:
        answer.points = 0
        answer.check_state = 'error'

    answer.check_comment = _strip_nul_chars(data.get('comment'))
    db.session.commit()

    # Emit WebSocket update
    from manage import socketio
    socketio.emit('answer_checked', {
        'answer_id': answer.id,
        'question_id': answer.question_id,
        'points': answer.points,
        'check_state': answer.check_state,
        'check_comment': answer.check_comment,
    }, room=f'attempt_{answer.attempt_id}')

    from celery_tasks.check_answer import _finalize_attempt_if_done
    _finalize_attempt_if_done(answer.attempt_id)

    return jsonify({'status': 'ok'})
