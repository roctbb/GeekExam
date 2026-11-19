"""Require a current LAN proof before admitting a browser to a Guard-protected test."""
from dataclasses import dataclass
from uuid import uuid4

from flask import abort, current_app, jsonify, session
from itsdangerous import BadData, URLSafeTimedSerializer

import guard_client
import presence_service as presence
from models import db
from presence_models import AttemptPresence, PresenceConfig, PresenceEvent


PROOF_LIFETIME = 45
AUTHORIZATION_MESSAGE = 'Авторизуйте это устройство в сети кабинета через Guard и попробуйте снова.'


def admission_error(message=AUTHORIZATION_MESSAGE, status=403):
    response = jsonify(error=message, error_code='guard_authorization_required')
    response.status_code = status
    response.headers['Cache-Control'] = 'no-store'
    return response


def requires_guard(config):
    return bool(config and config.require_guard)


def attempt_access_allowed(attempt):
    if attempt.finished_at:
        return True
    config = db.session.get(PresenceConfig, attempt.test_id)
    if not requires_guard(config):
        return True
    state = db.session.get(AttemptPresence, attempt.id)
    return bool(state and state.guard_session_id and
                [attempt.id, attempt.user_id, config.version, state.guard_session_id] in session.get('guard_attempts', []))


@dataclass(frozen=True)
class Admission:
    test_id: int
    user_id: int
    version: int
    room_id: str
    actor_id: int

    @classmethod
    def for_test(cls, test, config, user_id):
        if not config.guard_room_id or not config.configured_by:
            abort(admission_error('Для теста с Guard преподаватель должен выбрать кабинет.', 409))
        return cls(test.id, user_id, config.version, config.guard_room_id, config.configured_by)

    def proof_payload(self, client_id):
        return dict(test_id=self.test_id, user_id=self.user_id, room_id=self.room_id, client_id=client_id)

    def ticket_context(self):
        return [self.test_id, self.user_id, self.version, session.get('guard_join_nonce')]


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='geekexam-guard-admission')


def start_proof(admission):
    client_id = str(uuid4())
    db.session.rollback()
    try:
        data = guard_client.call('proofs/start', admission.actor_id, **admission.proof_payload(client_id))
    except guard_client.GuardUnavailable as failure:
        return _guard_error(failure)
    if data.get('state') == 'wait':
        return admission_error('Выполняется проверка Guard. Попробуйте войти ещё раз через несколько секунд.', 429)
    items = data.get('items')
    if data.get('state') != 'ready' or not isinstance(items, list) or not 1 <= len(items) <= 4:
        return admission_error('Не удалось начать проверку Guard. Проверьте подключение к сети кабинета.', 503)
    if any(not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key]
                                            for key in ('id', 'url', 'token')) for item in items):
        return admission_error('Guard вернул неверные данные проверки.', 503)
    session.setdefault('guard_join_nonce', str(uuid4()))
    ticket = _serializer().dumps({
        'context': admission.ticket_context(), 'client_id': client_id, 'proof_ids': [item['id'] for item in items],
    })
    response = jsonify(guard_proof={'ticket': ticket, 'items': items})
    response.headers['Cache-Control'] = 'no-store'
    return response, 202


def _guard_error(failure):
    if failure.reason == 'access_denied':
        return admission_error()
    return admission_error('Не удалось проверить авторизацию в Guard. Повторите попытку.', 503)


def consume_proof(admission, ticket, proof_ids):
    if (not isinstance(ticket, str) or len(ticket) > 2048 or not isinstance(proof_ids, list)
            or not 1 <= len(proof_ids) <= 4
            or any(not isinstance(proof_id, str) or not 1 <= len(proof_id) <= 36 for proof_id in proof_ids)):
        abort(admission_error())
    try:
        claims = _serializer().loads(ticket, max_age=PROOF_LIFETIME)
    except BadData:
        abort(admission_error('Подтверждение Guard истекло. Войдите в тест ещё раз.'))
    if claims['context'] != admission.ticket_context() or not set(proof_ids) <= set(claims['proof_ids']):
        abort(admission_error())

    db.session.rollback()
    for proof_id in dict.fromkeys(proof_ids):
        try:
            candidate = guard_client.call('proofs/consume', admission.actor_id, proof_id=proof_id,
                                          **admission.proof_payload(claims['client_id']))
        except guard_client.GuardUnavailable as failure:
            if failure.reason == 'proof_not_ready':
                continue
            abort(_guard_error(failure))
        if confirmed_evidence(candidate, admission.user_id):
            return candidate, proof_id
    abort(admission_error())


def confirmed_evidence(candidate, user_id):
    if (candidate.get('user_id') != user_id or candidate.get('method') != 'browser_lan_proof'
            or candidate.get('authorized') is not True):
        return None
    if any(not isinstance(candidate.get(key), str) or not 1 <= len(candidate[key]) <= 36
           for key in ('session_id', 'device_id', 'router_id')):
        return None
    try:
        observed = presence.parse(candidate.get('last_confirmed_at'))
        proved = presence.parse(candidate.get('proved_at'))
    except (ValueError, TypeError, AttributeError):
        return None
    at = presence.now()
    if (observed and proved and 0 <= (at - observed).total_seconds() <= presence.GUARD_TTL
            and 0 <= (at - proved).total_seconds() <= PROOF_LIFETIME):
        return observed, proved
    return None


def record_binding(attempt, admission, candidate, proof_id):
    evidence = confirmed_evidence(candidate, admission.user_id)
    if not evidence:
        abort(admission_error('Подтверждение Guard истекло. Войдите в тест ещё раз.'))
    observed, _ = evidence
    state = presence.ensure_attempt(attempt)
    confirmed_at = presence.now()
    if state.guard_session_id == candidate['session_id']:
        already_recorded = db.session.scalar(db.select(db.exists().where(
            PresenceEvent.attempt_id == attempt.id, presence.guard_admission_event(),
        )))
        if already_recorded:
            return
    else:
        if state.guard_session_id:
            presence.close_guard_gaps(attempt)
        state.guard_session_id, state.guard_device_id, state.guard_router_id = (
            candidate['session_id'], candidate['device_id'], candidate['router_id'],
        )
        state.bound_client_id, state.bound_by = None, admission.actor_id
        state.binding_confirmed_at, state.binding_observed_at = confirmed_at, observed
        state.guard_checked_at, state.guard_last_confirmed_at = confirmed_at, observed
        state.guard_state, state.guard_reason, state.guard_since = 'online', None, None
    presence.event(attempt.test_id, 'admission:' + proof_id, 'binding_confirmed', confirmed_at, attempt_id=attempt.id,
                   details={'method': 'browser_lan_proof', 'proof_id': proof_id})


def remember_admission(attempt, admission, candidate):
    entry = [attempt.id, attempt.user_id, admission.version, candidate['session_id']]
    entries = [row for row in session.get('guard_attempts', []) if row[0] != attempt.id]
    session['guard_attempts'] = entries[-11:] + [entry]
