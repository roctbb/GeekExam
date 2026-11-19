"""Attempt presence: authenticated evidence, separate from answer submission."""
import hashlib
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, abort, jsonify, request
from sqlalchemy.orm.exc import StaleDataError

from auth import api_login_required, teacher_required, current_user_id
from models import db, Attempt, Test
from presence_models import PresenceClient, PresenceHeartbeat, PresenceConfig, PresenceEvent, AttemptPresence
import guard_client
from guard_admission import admission_error, attempt_access_allowed, requires_guard
import presence_service as service
from time_utils import utc_iso

presence_bp = Blueprint('presence', __name__, url_prefix='/api')


@presence_bp.after_request
def private_connection_evidence(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def body(allowed):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - set(allowed):
        abort(422)
    # SameSite cookies plus an origin check for browser mutations.
    origin = request.headers.get('Origin')
    if origin and (urlsplit(origin).scheme not in {'http', 'https'} or urlsplit(origin).netloc != request.host):
        abort(403)
    return data


def attempt_for_owner(attempt_id):
    attempt = db.session.execute(db.select(Attempt).where(Attempt.id == attempt_id).with_for_update()).scalar_one_or_none()
    if not attempt:
        abort(404)
    if attempt.user_id != current_user_id():
        abort(403)
    if attempt.finished_at:
        abort(410)
    if not attempt_access_allowed(attempt):
        abort(admission_error())
    return attempt


def valid_client(attempt, data):
    client_id, token = data.get('client_id'), data.get('token')
    if not isinstance(client_id, str) or not isinstance(token, str) or len(token) > 128:
        abort(422)
    client = db.session.get(PresenceClient, client_id)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not client or client.attempt_id != attempt.id or not secrets.compare_digest(client.token_digest, digest):
        abort(403)
    return client


@presence_bp.post('/attempts/<int:attempt_id>/presence/clients')
@api_login_required
def register_client(attempt_id):
    data = body({'client_id', 'token'})
    # Lock the test before creating its one monitoring configuration.
    attempt = db.session.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != current_user_id():
        abort(404 if not attempt else 403)
    test = db.session.execute(db.select(Test).where(Test.id == attempt.test_id).with_for_update()).scalar_one()
    attempt = attempt_for_owner(attempt_id)
    config = service.ensure_config(test)
    if not config.enabled:
        return jsonify(enabled=False)
    token = None
    if data:
        client = valid_client(attempt, data)
    else:
        count = db.session.scalar(db.select(db.func.count()).select_from(PresenceClient).where(PresenceClient.attempt_id == attempt_id))
        if count >= 16:
            return jsonify(error='Слишком много подключений к этой попытке. Используйте ранее открытую вкладку.'), 409
        token = secrets.token_urlsafe(32)
        client = PresenceClient(attempt_id=attempt_id, token_digest=hashlib.sha256(token.encode()).hexdigest(),
                                created_at=service.now(), last_seen_at=service.now())
        db.session.add(client)
    if requires_guard(config):
        state = db.session.get(AttemptPresence, attempt_id)
        if state and not state.bound_client_id:
            db.session.flush()
            state.bound_client_id = client.id
    db.session.commit()
    return jsonify(enabled=True, client_id=client.id, code=client.id[:8].upper(), token=token,
                   next_sequence=client.last_sequence + 1, interval_seconds=5)


@presence_bp.post('/attempts/<int:attempt_id>/presence/heartbeat')
@api_login_required
def heartbeat(attempt_id):
    data = body({'client_id', 'token', 'sequence', 'visible'})
    attempt = attempt_for_owner(attempt_id)
    client = valid_client(attempt, data)
    config = db.session.get(PresenceConfig, attempt.test_id)
    if not config or not config.enabled:
        return jsonify(enabled=False)
    sequence = data.get('sequence')
    if type(sequence) is not int or not 1 <= sequence <= 2147483647 or type(data.get('visible')) is not bool:
        abort(422)
    if sequence == client.last_sequence:
        return jsonify(enabled=True, accepted=True, replay=True, received_at=utc_iso(client.last_seen_at))
    if sequence != client.last_sequence + 1:
        return jsonify(error='sequence_conflict', next_sequence=client.last_sequence + 1), 409
    at = service.now()
    # Capture an elapsed gap before refreshing last_seen_at.
    service.update_exam_gaps(attempt, at)
    client.last_seen_at, client.last_sequence, client.visible = at, sequence, data['visible']
    db.session.add(PresenceHeartbeat(attempt_id=attempt_id, client_id=client.id, sequence=sequence,
                                    received_at=at, visible=client.visible))
    db.session.flush()
    service.update_exam_gaps(attempt, at)
    db.session.commit()
    return jsonify(enabled=True, accepted=True, received_at=utc_iso(at))


@presence_bp.get('/presence/rooms')
@teacher_required
def rooms():
    try:
        return jsonify(guard_client.call('rooms', current_user_id()))
    except guard_client.GuardUnavailable:
        return jsonify(error='Не удалось получить кабинеты из Guard. Изменения не отправлены.'), 503


@presence_bp.get('/tests/<int:test_id>/presence')
@teacher_required
def snapshot(test_id):
    return jsonify(service.snapshot(db.get_or_404(Test, test_id)))


@presence_bp.get('/tests/<int:test_id>/presence/settings')
@teacher_required
def settings(test_id):
    db.get_or_404(Test, test_id)
    return jsonify(service.settings_view(db.session.get(PresenceConfig, test_id)))


@presence_bp.put('/tests/<int:test_id>/presence')
@teacher_required
def configure(test_id):
    data = body({'version', 'enabled', 'room_id', 'require_guard'})
    if type(data.get('version')) is not int or type(data.get('enabled')) is not bool:
        abort(422)
    if 'require_guard' in data and type(data['require_guard']) is not bool:
        abort(422)
    room_id = data.get('room_id')
    if room_id is not None and (not isinstance(room_id, str) or not 1 <= len(room_id) <= 36):
        abort(422)
    test = db.get_or_404(Test, test_id)
    config = db.session.get(PresenceConfig, test_id)
    if data['version'] != (config.version if config else 0):
        return jsonify(error='Настройки уже изменены. Обновите страницу.'), 409
    require_guard = data.get('require_guard', requires_guard(config))
    if require_guard and not room_id:
        return jsonify(error='Выберите кабинет для проверки авторизации в Guard.'), 422
    room_name = None
    if require_guard:
        try:
            room_data = guard_client.call('rooms', current_user_id(), room_id=room_id)
            room_name = str(room_data['room']['name'])[:120]
        except (guard_client.GuardUnavailable, KeyError, TypeError):
            return jsonify(error='Кабинет недоступен. Настройки не изменены.'), 503
    # Serialize first configuration creation, then recheck the optimistic version.
    db.session.execute(db.select(Test).where(Test.id == test_id).with_for_update()).scalar_one()
    db.session.expire_all()
    config = db.session.get(PresenceConfig, test_id)
    if data['version'] != (config.version if config else 0):
        return jsonify(error='Настройки уже изменены. Обновите страницу.'), 409
    config = config or service.ensure_config(test)
    if config.guard_room_id != room_id or (config.require_guard and not require_guard):
        attempts = db.session.execute(db.select(Attempt).where(Attempt.test_id == test_id).order_by(Attempt.id).with_for_update()).scalars()
        for attempt in attempts:
            state = db.session.get(AttemptPresence, attempt.id)
            if state and state.guard_session_id:
                service.close_guard_gaps(attempt)
                service.event(test_id, 'unbind:' + str(attempt.id) + ':' + utc_iso(service.now()), 'binding_changed',
                              service.now(), attempt_id=attempt.id, details={'reason':'monitor_configuration_changed'})
                state.guard_session_id = state.bound_client_id = None
                state.guard_state, state.guard_reason = 'unbound', 'monitor_configuration_changed'
    config.guard_room_id, config.enabled = room_id, data['enabled']
    config.require_guard = require_guard
    config.guard_room_name = room_name
    config.configured_by, config.updated_at = current_user_id(), service.now()
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        return jsonify(error='Настройки уже изменены. Обновите страницу.'), 409
    return jsonify(service.snapshot(test))


@presence_bp.get('/attempts/<int:attempt_id>/presence/candidates')
@teacher_required
def candidates(attempt_id):
    attempt = db.get_or_404(Attempt, attempt_id)
    config = db.session.get(PresenceConfig, attempt.test_id)
    if not requires_guard(config) or not config.guard_room_id:
        return jsonify(error='Сначала включите проверку Guard и выберите кабинет.'), 422
    try:
        return jsonify(guard_client.call('rooms', current_user_id(), room_id=config.guard_room_id, user_id=attempt.user_id))
    except guard_client.GuardUnavailable:
        return jsonify(error='Guard недоступен или кабинет не назначен преподавателю.'), 503


@presence_bp.post('/attempts/<int:attempt_id>/presence/binding')
@teacher_required
def bind(attempt_id):
    data = body({'session_id', 'client_id', 'confirmed'})
    if data.get('confirmed') is not True:
        abort(422)
    attempt = db.get_or_404(Attempt, attempt_id)
    config = db.session.get(PresenceConfig, attempt.test_id)
    if attempt.finished_at or not requires_guard(config) or not config.enabled or not config.guard_room_id:
        abort(409)
    version = config.version
    try:
        candidates = guard_client.call('rooms', current_user_id(), room_id=config.guard_room_id, user_id=attempt.user_id)
    except guard_client.GuardUnavailable:
        return jsonify(error='Guard недоступен. Устройство не привязано.'), 503
    candidate = next((item for item in candidates.get('candidates', []) if item.get('session_id') == data.get('session_id')
                      and item.get('user_id') == attempt.user_id), None)
    if not candidate:
        return jsonify(error='Нет действующей сетевой сессии этого ученика. Обновите список.'), 409
    # Config changes, finishing and heartbeats cannot race this commit.
    db.session.execute(db.select(Test).where(Test.id == attempt.test_id).with_for_update()).scalar_one()
    db.session.expire_all()
    config = db.session.get(PresenceConfig, attempt.test_id)
    attempt = db.session.execute(db.select(Attempt).where(Attempt.id == attempt_id).with_for_update()).scalar_one()
    if attempt.finished_at or config.version != version or not config.enabled:
        abort(409)
    client = db.session.get(PresenceClient, data.get('client_id')) if isinstance(data.get('client_id'), str) else None
    if not client or client.attempt_id != attempt_id or (service.now()-client.last_seen_at).total_seconds() > service.HEARTBEAT_TTL:
        return jsonify(error='Выберите активное подключение GeekExam по коду на экране ученика.'), 409
    observed = service.parse(candidate['last_confirmed_at'])
    if not observed or not 0 <= (service.now()-observed).total_seconds() <= service.GUARD_TTL:
        return jsonify(error='Данные об устройстве устарели. Обновите список.'), 409
    state = service.ensure_attempt(attempt)
    service.close_guard_gaps(attempt)
    state.guard_session_id, state.guard_device_id, state.guard_router_id = candidate['session_id'], candidate['device_id'], candidate['router_id']
    state.bound_client_id, state.bound_by = client.id, current_user_id()
    state.binding_confirmed_at = state.guard_checked_at = service.now()
    state.binding_observed_at = state.guard_last_confirmed_at = observed
    state.guard_state, state.guard_reason, state.guard_since = 'online', None, None
    service.event(attempt.test_id, 'bind:' + str(attempt_id) + ':' + utc_iso(service.now()), 'binding_confirmed',
                  service.now(), attempt_id=attempt_id, details={'client_code':client.id[:8].upper(), 'confirmed_by':current_user_id()})
    db.session.commit()
    return jsonify(ok=True)


@presence_bp.get('/attempts/<int:attempt_id>/presence/events')
@teacher_required
def history(attempt_id):
    attempt = db.get_or_404(Attempt, attempt_id)
    rows = db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id == attempt.test_id,
        db.or_(PresenceEvent.attempt_id == attempt_id, PresenceEvent.attempt_id.is_(None)))
        .order_by(PresenceEvent.started_at.desc()).limit(500)).scalars().all()
    return jsonify(items=[service.event_view(row) for row in rows], limit=500)


@presence_bp.post('/presence/events/<event_id>/review')
@teacher_required
def review(event_id):
    data = body({'note'})
    note = data.get('note', '')
    if not isinstance(note, str) or len(note) > 500:
        abort(422)
    row = db.get_or_404(PresenceEvent, event_id)
    if not row.review_required:
        abort(409)
    row.reviewed_at, row.reviewed_by, row.review_note = service.now(), current_user_id(), note.strip()
    db.session.commit()
    return jsonify(service.event_view(row))
