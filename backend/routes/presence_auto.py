"""Bind a browser attempt only after the registered LAN agent proves its source."""
from flask import abort, jsonify

from auth import api_login_required, current_user_id
from models import db, Attempt, Test
from presence_models import PresenceConfig, AttemptPresence
from .presence import presence_bp, body, valid_client, needs_new_proof
import guard_client
from guard_admission import Admission, remember_admission, record_binding, admission_error, attempt_access_allowed, confirmed_evidence, requires_guard
import presence_service as service


def context(attempt_id, data):
    attempt = db.get_or_404(Attempt, attempt_id)
    if attempt.user_id != current_user_id():
        abort(403)
    if attempt.finished_at:
        abort(410)
    if not attempt_access_allowed(attempt):
        abort(admission_error())
    client = valid_client(attempt,data)
    if (service.now()-client.last_seen_at).total_seconds() > service.HEARTBEAT_TTL:
        abort(409)
    config = db.session.get(PresenceConfig,attempt.test_id)
    return attempt,client,config


@presence_bp.post('/attempts/<int:attempt_id>/presence/auto/start')
@api_login_required
def start(attempt_id):
    data = body({'client_id','token'})
    attempt,client,config = context(attempt_id,data)
    if not requires_guard(config) or not config.enabled or not config.guard_room_id:
        return jsonify(state='disabled',reason='room_not_configured',items=[])
    state = db.session.get(AttemptPresence,attempt_id)
    if state and state.guard_session_id and state.bound_client_id == client.id and not needs_new_proof(state, client):
        return jsonify(state='bound',items=[])
    payload = {'room_id':config.guard_room_id,'user_id':attempt.user_id,'attempt_id':attempt.id,
               'client_id':client.id,'require_authorized':True}
    actor_id = config.configured_by
    # Proof network IO must never hold an attempt lock or delay answer saving.
    db.session.rollback()
    try:
        return jsonify(guard_client.call('proofs/start',actor_id,**payload))
    except guard_client.GuardUnavailable:
        return jsonify(state='unavailable',reason='guard_unavailable',items=[])


@presence_bp.post('/attempts/<int:attempt_id>/presence/auto/finish')
@api_login_required
def finish(attempt_id):
    data = body({'client_id','token','proof_id'})
    if not isinstance(data.get('proof_id'),str) or len(data['proof_id']) > 36:
        abort(422)
    attempt,client,config = context(attempt_id,data)
    if not requires_guard(config) or not config.enabled or not config.guard_room_id:
        abort(409)
    test_id,room_id,version,actor_id = attempt.test_id,config.guard_room_id,config.version,config.configured_by
    user_id,client_id = attempt.user_id,client.id
    db.session.rollback()
    try:
        candidate = guard_client.call('proofs/consume',actor_id,room_id=room_id,user_id=user_id,
            attempt_id=attempt_id,client_id=client_id,proof_id=data['proof_id'],require_authorized=True)
    except guard_client.GuardUnavailable:
        return jsonify(state='unavailable',error='Сетевое подтверждение не получено. Привязка не изменена.'),409
    evidence = confirmed_evidence(candidate, user_id)
    if not evidence:
        abort(409)
    observed, proved = evidence
    db.session.execute(db.select(Test).where(Test.id==test_id).with_for_update()).scalar_one()
    db.session.expire_all()
    attempt = db.session.execute(db.select(Attempt).where(Attempt.id==attempt_id).with_for_update()).scalar_one()
    config = db.session.get(PresenceConfig,test_id)
    if attempt.finished_at:
        abort(410)
    if not requires_guard(config) or not config.enabled or config.version != version or config.guard_room_id != room_id:
        abort(409)
    state = service.ensure_attempt(attempt)
    if state.guard_session_id:
        if state.guard_device_id != candidate['device_id'] or state.guard_router_id != candidate['router_id']:
            event = service.event(test_id,'device-mismatch:'+data['proof_id'],'device_mismatch',proved,
                attempt_id=attempt_id,details={'client_code':client_id[:8].upper(),'method':'browser_lan_proof'})
            event.review_required = True
            db.session.commit()
            return jsonify(state='different_device',error='Эта попытка уже привязана к другому устройству. Сообщите преподавателю.'),409
        if needs_new_proof(state, client) and state.guard_session_id != candidate['session_id']:
            if not attempt_access_allowed(attempt):
                abort(admission_error())
            admission = Admission.for_test(attempt.test, config, user_id)
            record_binding(attempt, admission, candidate, data['proof_id'])
            state.bound_client_id = client_id
            db.session.commit()
            remember_admission(attempt, admission, candidate)
            return jsonify(state='bound')
        db.session.commit()
        return jsonify(state='bound')
    state.guard_session_id,state.guard_device_id,state.guard_router_id = candidate['session_id'],candidate['device_id'],candidate['router_id']
    state.bound_client_id,state.bound_by = client_id,actor_id
    state.binding_confirmed_at,state.binding_observed_at = service.now(),observed
    state.guard_checked_at,state.guard_last_confirmed_at = service.now(),observed
    state.guard_state,state.guard_reason,state.guard_since = 'online',None,None
    service.event(test_id,'auto-bind:'+data['proof_id'],'binding_confirmed',proved,attempt_id=attempt_id,
        details={'method':'browser_lan_proof','client_code':client_id[:8].upper(),'proof_id':data['proof_id']})
    db.session.commit()
    return jsonify(state='bound')
