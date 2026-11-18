"""Bind a browser attempt only after the registered LAN agent proves its source."""
from flask import abort, jsonify

from auth import api_login_required, current_user_id
from models import db, Attempt, Test
from presence_models import PresenceConfig, AttemptPresence
from .presence import presence_bp, body, valid_client
import guard_client
import presence_service as service
from time_utils import utc_iso


def context(attempt_id, data):
    attempt = db.get_or_404(Attempt, attempt_id)
    if attempt.user_id != current_user_id():
        abort(403)
    if attempt.finished_at:
        abort(410)
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
    if not config or not config.enabled or not config.guard_room_id:
        return jsonify(state='disabled',reason='room_not_configured',items=[])
    state = db.session.get(AttemptPresence,attempt_id)
    if state and state.guard_session_id and state.bound_client_id == client.id:
        return jsonify(state='bound',items=[])
    payload = {'room_id':config.guard_room_id,'user_id':attempt.user_id,'attempt_id':attempt.id,'client_id':client.id}
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
    if not config or not config.enabled or not config.guard_room_id:
        abort(409)
    test_id,room_id,version,actor_id = attempt.test_id,config.guard_room_id,config.version,config.configured_by
    user_id,client_id = attempt.user_id,client.id
    db.session.rollback()
    try:
        candidate = guard_client.call('proofs/consume',actor_id,room_id=room_id,user_id=user_id,
            attempt_id=attempt_id,client_id=client_id,proof_id=data['proof_id'])
    except guard_client.GuardUnavailable:
        return jsonify(state='unavailable',error='Сетевое подтверждение не получено. Привязка не изменена.'),409
    if candidate.get('user_id') != user_id or candidate.get('method') != 'browser_lan_proof':
        abort(409)
    observed = service.parse(candidate.get('last_confirmed_at'))
    proved = service.parse(candidate.get('proved_at'))
    if not observed or not proved or not 0 <= (service.now()-observed).total_seconds() <= service.GUARD_TTL or not 0 <= (service.now()-proved).total_seconds() <= 45:
        abort(409)
    if any(not isinstance(candidate.get(key),str) or not 1 <= len(candidate[key]) <= 36 for key in ['session_id','device_id','router_id']):
        abort(409)
    db.session.execute(db.select(Test).where(Test.id==test_id).with_for_update()).scalar_one()
    db.session.expire_all()
    attempt = db.session.execute(db.select(Attempt).where(Attempt.id==attempt_id).with_for_update()).scalar_one()
    config = db.session.get(PresenceConfig,test_id)
    if attempt.finished_at:
        abort(410)
    if not config.enabled or config.version != version or config.guard_room_id != room_id:
        abort(409)
    state = service.ensure_attempt(attempt)
    if state.guard_session_id:
        if state.guard_device_id != candidate['device_id'] or state.guard_router_id != candidate['router_id']:
            event = service.event(test_id,'device-mismatch:'+data['proof_id'],'device_mismatch',proved,
                attempt_id=attempt_id,details={'client_code':client_id[:8].upper(),'method':'browser_lan_proof'})
            event.review_required = True
            db.session.commit()
            return jsonify(state='different_device',error='Эта попытка уже привязана к другому устройству. Сообщите преподавателю.'),409
        # Keep the original observation window and sticky loss evidence intact.
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
