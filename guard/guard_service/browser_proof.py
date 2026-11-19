"""A proof must originate from the actual LAN socket, not a browser-supplied IP."""
from datetime import timedelta
import ipaddress
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify

from .models import db, BrowserProof, LocalProofEndpoint, Device, NetworkSession, Router, StudentRoom, User
from .security import ApiError, authenticated, body, digest, integer, now, text
from .routes import authorize_room, audit, is_fresh
from .agents import authenticate_agent
from .exam_presence import actor, exam_presence
from .policy import active_session, stamp

proof_api = Blueprint('browser_proof', __name__, url_prefix='/api/v1')


def https_origin(value):
    value = text(value, 250)
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ApiError('https_origin_required')
    try:
        parsed.port
    except ValueError:
        raise ApiError('invalid_endpoint_port') from None
    try:
        address = ipaddress.ip_address(parsed.hostname)
        if address.is_loopback or address.is_unspecified or address.is_multicast or not address.is_private:
            raise ApiError('local_endpoint_required')
    except ValueError:
        # A DNS name must resolve to the private LAN endpoint on student devices.
        if parsed.hostname in {'localhost'}:
            raise ApiError('local_endpoint_required')
    if value.rstrip('/') in {current_app.config['PUBLIC_URL'].rstrip('/'), current_app.config['EXAM_ORIGIN']}:
        raise ApiError('separate_lan_origin_required')
    return value.rstrip('/')


@proof_api.get('/routers/<router_id>/browser-proof')
@authenticated('admin')
def endpoint_get(router_id):
    db.get_or_404(Router, router_id)
    endpoint = db.session.get(LocalProofEndpoint, router_id)
    return jsonify(origin=endpoint.origin if endpoint else '', enabled=endpoint.enabled if endpoint else False,
                   version=endpoint.version if endpoint else 0)


@proof_api.put('/routers/<router_id>/browser-proof')
@authenticated('admin')
def endpoint_set(router_id):
    data = body({'origin', 'enabled', 'version'}, {'origin', 'enabled', 'version'})
    router = db.session.execute(db.select(Router).where(Router.id == router_id).with_for_update()).scalar_one_or_none()
    if not router:
        raise ApiError('not_found', 404)
    if type(data['enabled']) is not bool or type(data['version']) is not int:
        raise ApiError('invalid_fields')
    origin = https_origin(data['origin'])
    row = db.session.get(LocalProofEndpoint, router_id)
    if data['version'] != (row.version if row else 0):
        raise ApiError('conflict_refresh_required', 409)
    if row is None:
        row = LocalProofEndpoint(router_id=router_id, origin=origin)
        db.session.add(row)
    row.origin, row.enabled = origin, data['enabled']
    audit(router.room_id, 'router.browser_proof_configured', router.id, {'origin':origin, 'enabled':row.enabled})
    db.session.commit()
    return jsonify(origin=row.origin, enabled=row.enabled, version=row.version)


def proof_target(data):
    if 'test_id' in data:
        if 'attempt_id' in data or 'require_authorized' in data:
            raise ApiError('invalid_proof_target')
        return 'test', integer(data['test_id'])
    require_authorized = data.get('require_authorized', False)
    if 'attempt_id' not in data or type(require_authorized) is not bool:
        raise ApiError('invalid_proof_target')
    return ('authorized_attempt' if require_authorized else 'attempt'), integer(data['attempt_id'])


@exam_presence.post('/proofs/start')
def start():
    data = body({'actor_id', 'room_id', 'user_id', 'attempt_id', 'test_id', 'require_authorized', 'client_id'},
                {'actor_id', 'room_id', 'user_id', 'client_id'})
    teacher = actor(data)
    room = authorize_room(text(data['room_id'], 36), teacher)
    user = db.session.get(User, integer(data['user_id']))
    if not user or user.role_expires_at <= now():
        raise ApiError('identity_refresh_required', 409)
    if teacher.role != 'admin' and user.id != teacher.id and (user.role != 'student' or not db.session.get(StudentRoom,(room.id,user.id))):
        raise ApiError('forbidden',403)
    scope, target_id = proof_target(data)
    client_id = text(data['client_id'], 36)
    if scope == 'test':
        db.session.execute(db.select(User.id).where(User.id == user.id).with_for_update()).scalar_one()
        rounds = db.session.scalar(db.select(db.func.count(db.distinct(BrowserProof.client_id))).where(
            BrowserProof.user_id == user.id, BrowserProof.scope == scope, BrowserProof.target_id == target_id,
            BrowserProof.expires_at > now(), BrowserProof.consumed_at.is_(None),
        ))
        if rounds >= 8:
            return jsonify(state='wait', retry_after_seconds=45, items=[])
    db.session.execute(db.delete(BrowserProof).where(BrowserProof.expires_at < now()-timedelta(days=1)))
    # One bounded set per browser client, with no user credentials in LAN tokens.
    active = db.session.scalar(db.select(db.func.count()).select_from(BrowserProof).where(
        BrowserProof.client_id == client_id, BrowserProof.expires_at > now()))
    if active:
        return jsonify(state='wait', retry_after_seconds=45, items=[])
    endpoints = db.session.execute(db.select(LocalProofEndpoint).join(Router).where(
        Router.room_id == room.id, LocalProofEndpoint.enabled.is_(True)).order_by(Router.id).limit(5)).scalars().all()
    if len(endpoints) > 4:
        raise ApiError('too_many_lan_endpoints', 409)
    items = []
    for endpoint in endpoints:
        router = db.session.get(Router, endpoint.router_id)
        if not is_fresh(router):
            continue
        token = secrets.token_urlsafe(32)
        row = BrowserProof(token_digest=digest(token), room_id=room.id, router_id=router.id, user_id=user.id,
            actor_id=teacher.id, target_id=target_id, scope=scope, client_id=client_id,
            browser_origin=current_app.config['EXAM_ORIGIN'],
            endpoint_origin=endpoint.origin, expires_at=now()+timedelta(seconds=45))
        db.session.add(row); db.session.flush()
        items.append({'id':row.id, 'token':token, 'url':endpoint.origin+'/v1/browser-proof'})
    db.session.commit()
    return jsonify(state='ready' if items else 'unavailable' if endpoints else 'not_configured', items=items, expires_in_seconds=45)


def agent_proof(data):
    router = authenticate_agent()
    token = text(data.get('token'), 100)
    row = db.session.execute(db.select(BrowserProof).where(BrowserProof.token_digest == digest(token)).with_for_update()).scalar_one_or_none()
    if not row or row.router_id != router.id or row.expires_at <= now() or row.consumed_at:
        raise ApiError('invalid_or_expired_proof', 409)
    endpoint = db.session.get(LocalProofEndpoint, router.id)
    if router.room_id != row.room_id or not endpoint or not endpoint.enabled or endpoint.origin != row.endpoint_origin:
        raise ApiError('endpoint_changed', 409)
    if data.get('origin') != row.browser_origin or data.get('endpoint_origin') != row.endpoint_origin:
        raise ApiError('origin_mismatch', 403)
    teacher = db.session.get(User,row.actor_id)
    if not teacher or teacher.role not in {'teacher','admin'} or teacher.role_expires_at <= now():
        raise ApiError('forbidden',403)
    authorize_room(row.room_id,teacher)
    user = db.session.get(User,row.user_id)
    if not user or user.role_expires_at <= now():
        raise ApiError('identity_refresh_required',409)
    if teacher.role != 'admin' and user.id != teacher.id and (user.role != 'student' or not db.session.get(StudentRoom,(row.room_id,user.id))):
        raise ApiError('forbidden',403)
    return row, router


@proof_api.post('/agent/proofs/inspect')
def inspect_proof():
    data = body({'token', 'origin', 'endpoint_origin'}, {'token', 'origin', 'endpoint_origin'})
    row, _router = agent_proof(data)
    return jsonify(id=row.id, expires_at=stamp(row.expires_at))


@proof_api.post('/agent/proofs/complete')
def complete():
    data = body({'token', 'origin', 'endpoint_origin', 'peer_ip', 'mac', 'epoch', 'boot_id', 'source_age_seconds'},
                {'token', 'origin', 'endpoint_origin', 'peer_ip', 'mac', 'epoch', 'boot_id', 'source_age_seconds'})
    row, router = agent_proof(data)
    try:
        address = ipaddress.IPv4Address(data['peer_ip'])
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError()
    except (ValueError, TypeError):
        raise ApiError('invalid_lan_peer') from None
    if integer(data['source_age_seconds'], 0, 60) > 10 or not is_fresh(router) or data['boot_id'] != router.boot_id:
        raise ApiError('fresh_observation_required', 409)
    devices = db.session.execute(db.select(Device).where(Device.router_id == router.id,
        Device.ip == str(address), Device.associated.is_(True))).scalars().all()
    if len(devices) != 1:
        raise ApiError('unique_lan_device_required', 409)
    device = devices[0]
    if data['mac'] != device.mac or data['epoch'] != device.epoch:
        raise ApiError('connection_changed', 409)
    user = db.session.get(User, row.user_id)
    if not user or user.role_expires_at <= now():
        raise ApiError('identity_refresh_required', 409)
    session = active_session(device, router)
    if row.scope != 'attempt' and (not session or session.user_id != user.id or session.expires_at <= now()
                                   or session.method == 'browser_lan_proof'):
        raise ApiError('device_not_authorized', 409)
    if row.completed_at:
        if row.device_id != device.id or row.epoch != device.epoch:
            raise ApiError('proof_already_completed', 409)
        return jsonify(id=row.id, state='proved')
    # No implicit assignment of a live device currently granted to another user.
    if session and session.expires_at > now() and not session.revoked_at and session.user_id != user.id:
        raise ApiError('device_has_another_user', 409)
    if not session or session.expires_at <= now() or session.revoked_at:
        session = NetworkSession(device_id=device.id, user_id=user.id, boot_id=router.boot_id, epoch=device.epoch,
            expires_at=now()+timedelta(hours=8), method='browser_lan_proof', created_by=row.actor_id)
        db.session.add(session); db.session.flush()
        router.desired_revision += 1
    row.device_id, row.session_id, row.boot_id, row.epoch = device.id, session.id, router.boot_id, device.epoch
    row.completed_at = now()
    # This is an exam-only proof; it must not grant a wider room membership.
    audit(router.room_id, 'session.browser_lan_proved', session.id, {'device_id':device.id, 'user_id':user.id, 'proof_id':row.id})
    db.session.commit()
    return jsonify(id=row.id, state='proved')


@exam_presence.post('/proofs/consume')
def consume():
    data = body({'actor_id', 'room_id', 'user_id', 'attempt_id', 'test_id', 'require_authorized', 'client_id', 'proof_id'},
                {'actor_id', 'room_id', 'user_id', 'client_id', 'proof_id'})
    teacher = actor(data)
    room = authorize_room(text(data['room_id'], 36), teacher)
    scope, target_id = proof_target(data)
    row = db.session.execute(db.select(BrowserProof).where(BrowserProof.id == text(data['proof_id'],36)).with_for_update()).scalar_one_or_none()
    if not row or (row.room_id, row.user_id, row.scope, row.target_id, row.client_id) != (
        room.id, integer(data['user_id']), scope, target_id, text(data['client_id'], 36)
    ):
        raise ApiError('invalid_proof', 403)
    if row.actor_id != teacher.id:
        raise ApiError('proof_authority_changed',403)
    if row.expires_at <= now() or not row.completed_at or (scope == 'test' and row.consumed_at):
        raise ApiError('proof_not_ready', 409)
    user = db.session.get(User,row.user_id)
    if not user or user.role_expires_at <= now():
        raise ApiError('identity_refresh_required',409)
    device = db.session.get(Device,row.device_id); router = db.session.get(Router,row.router_id)
    endpoint = db.session.get(LocalProofEndpoint,router.id)
    session = db.session.get(NetworkSession,row.session_id)
    if not endpoint or not endpoint.enabled or endpoint.origin != row.endpoint_origin or router.room_id != room.id:
        raise ApiError('endpoint_changed',409)
    if not is_fresh(router) or not device.associated or router.boot_id != row.boot_id or device.epoch != row.epoch or session.user_id != row.user_id or session.revoked_at or session.expires_at <= now() or active_session(device,router) != session:
        raise ApiError('fresh_observation_required',409)
    if scope != 'attempt' and session.method == 'browser_lan_proof':
        raise ApiError('device_not_authorized', 409)
    row.consumed_at = row.consumed_at or now()
    db.session.commit()
    return jsonify(session_id=session.id,user_id=row.user_id,device_id=device.id,router_id=router.id,
        last_confirmed_at=stamp(device.observed_at),proved_at=stamp(row.completed_at),method='browser_lan_proof',
        authorized=scope != 'attempt')
