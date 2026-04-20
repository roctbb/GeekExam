from flask import Blueprint, jsonify, request
import jwt
import time
import json
import hashlib
import redis
from models import db, Answer
from config import (
    JWT_SECRET,
    REDIS_URL,
    GEEKPASTE_CALLBACK_REQUIRE_AUTH,
    GEEKPASTE_CALLBACK_EXPECTED_SERVICE,
    GEEKPASTE_CALLBACK_MAX_AGE_SECONDS,
    GEEKPASTE_CALLBACK_DEDUP_TTL_SECONDS,
)

callbacks_bp = Blueprint('callbacks', __name__)
_redis_client = redis.from_url(REDIS_URL, decode_responses=True)


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


def _verify_callback_auth():
    if not GEEKPASTE_CALLBACK_REQUIRE_AUTH:
        return
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized callback'}), 401
    token = auth[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except Exception:
        return jsonify({'error': 'Unauthorized callback'}), 401
    if payload.get('service') != GEEKPASTE_CALLBACK_EXPECTED_SERVICE:
        return jsonify({'error': 'Forbidden callback source'}), 403
    iat = payload.get('iat')
    now = int(time.time())
    if not isinstance(iat, int):
        return jsonify({'error': 'Invalid callback token'}), 401
    # Allow slight clock skew into the future.
    if iat > now + 30:
        return jsonify({'error': 'Invalid callback token'}), 401
    if now - iat > GEEKPASTE_CALLBACK_MAX_AGE_SECONDS:
        return jsonify({'error': 'Expired callback token'}), 401
    return None


def _parse_callback_id(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value
    value = str(raw_value).strip()
    if value.isdigit():
        return int(value)
    if value.startswith('answer_') and value[7:].isdigit():
        return int(value[7:])
    return None


def _dedupe_key(data, answer_id):
    job_id = data.get('job_id')
    if job_id:
        return f'geekexam:callback:processed:{answer_id}:{job_id}'
    payload_str = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    return f'geekexam:callback:processed:{answer_id}:hash:{payload_hash}'


def _is_duplicate_callback(data, answer_id):
    key = _dedupe_key(data, answer_id)
    try:
        return _redis_client.exists(key) == 1
    except Exception:
        # Fail-open: do not block callback processing when Redis is unavailable.
        return False


def _mark_callback_processed(data, answer_id):
    key = _dedupe_key(data, answer_id)
    try:
        _redis_client.set(key, '1', ex=GEEKPASTE_CALLBACK_DEDUP_TTL_SECONDS)
    except Exception:
        pass


@callbacks_bp.route('/api/callback/check', methods=['POST'])
def check_callback():
    auth_error = _verify_callback_auth()
    if auth_error:
        return auth_error

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    answer_id = _parse_callback_id(data.get('callback_id'))
    if answer_id is None:
        return jsonify({'error': 'Missing callback_id'}), 400

    if _is_duplicate_callback(data, answer_id):
        return jsonify({'status': 'ok', 'duplicate': True})

    answer = Answer.query.get(answer_id)
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
    _mark_callback_processed(data, answer_id)

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
