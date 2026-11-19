"""SSO network login: browser parameters never select the device or its role."""
from datetime import timedelta
import ipaddress
import secrets

from flask import Blueprint, current_app, g, jsonify

from .models import (db, Device, LocalProofEndpoint, NetworkLogin, NetworkSession,
                     Router, Segment, StudentRoom, User)
from .agents import authenticate_agent
from .policy import active_session, stamp
from .routes import audit, device_state, is_fresh, router_state
from .security import ApiError, authenticated, body, digest, integer, now, text

network_login = Blueprint('network_login', __name__, url_prefix='/api/v1')


def endpoint_for(router_id):
    router = db.session.get(Router, router_id)
    endpoint = db.session.get(LocalProofEndpoint, router_id)
    if not router or not endpoint or not endpoint.enabled:
        raise ApiError('network_login_not_configured', 409)
    if not is_fresh(router):
        raise ApiError('router_unavailable', 503)
    return router, endpoint


@network_login.post('/network-login/start')
@authenticated()
def start():
    data = body({'router_id'}, {'router_id'})
    router, endpoint = endpoint_for(text(data['router_id'], 36))
    # Serialize concurrent starts for the same account; challenges last 45 seconds.
    db.session.execute(db.select(User).where(User.id == g.user.id).with_for_update()).scalar_one()
    db.session.execute(db.delete(NetworkLogin).where(NetworkLogin.expires_at < now()-timedelta(days=1)))
    count = db.session.scalar(db.select(db.func.count()).select_from(NetworkLogin).where(
        NetworkLogin.user_id == g.user.id, NetworkLogin.expires_at > now()))
    if count >= 8:
        raise ApiError('too_many_login_attempts', 429)
    token = secrets.token_urlsafe(32)
    row = NetworkLogin(token_digest=digest(token), user_id=g.user.id, router_id=router.id,
                       endpoint_origin=endpoint.origin, expires_at=now()+timedelta(seconds=45))
    db.session.add(row); db.session.flush()
    result = {'id': row.id, 'token': token, 'url': endpoint.origin+'/v1/network-login', 'expires_in_seconds': 45}
    db.session.commit()
    return jsonify(result), 201


def challenge(data):
    router = authenticate_agent()
    row = db.session.execute(db.select(NetworkLogin).where(
        NetworkLogin.token_digest == digest(text(data.get('token'), 100))).with_for_update()).scalar_one_or_none()
    if not row or row.router_id != router.id or row.expires_at <= now():
        raise ApiError('invalid_or_expired_proof', 409)
    _, endpoint = endpoint_for(router.id)
    if endpoint.origin != row.endpoint_origin or data.get('endpoint_origin') != row.endpoint_origin:
        raise ApiError('endpoint_changed', 409)
    if data.get('origin') != current_app.config['PUBLIC_URL'].rstrip('/'):
        raise ApiError('origin_mismatch', 403)
    user = db.session.get(User, row.user_id)
    if not user or user.role_expires_at <= now():
        raise ApiError('identity_refresh_required', 409)
    return row, router, user


@network_login.post('/agent/network-login/inspect')
def inspect():
    row, _, _ = challenge(body({'token','origin','endpoint_origin'}, {'token','origin','endpoint_origin'}))
    return jsonify(id=row.id, expires_at=stamp(row.expires_at))


@network_login.post('/agent/network-login/complete')
def complete():
    fields = {'token','origin','endpoint_origin','peer_ip','mac','epoch','boot_id','source_age_seconds'}
    data = body(fields, fields)
    row, router, user = challenge(data)
    try:
        address = ipaddress.IPv4Address(data['peer_ip'])
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError()
    except (ValueError, TypeError):
        raise ApiError('invalid_lan_peer') from None
    if integer(data['source_age_seconds'], 0, 60) > 10 or data['boot_id'] != router.boot_id:
        raise ApiError('fresh_observation_required', 409)
    devices = db.session.execute(db.select(Device).where(Device.router_id == router.id,
        Device.ip == str(address), Device.associated.is_(True)).with_for_update()).scalars().all()
    if len(devices) != 1:
        raise ApiError('unique_lan_device_required', 409)
    device = devices[0]
    segment = db.session.get(Segment, device.segment_id)
    if segment.purpose != 'student':
        raise ApiError('student_network_required', 409)
    if data['mac'] != device.mac or data['epoch'] != device.epoch:
        raise ApiError('connection_changed', 409)
    binding = active_session(device, router)
    if binding and binding.expires_at > now() and binding.user_id != user.id:
        raise ApiError('device_has_another_user', 409)
    if row.completed_at:
        if not binding or binding.id != row.session_id or binding.expires_at <= now():
            raise ApiError('proof_already_completed', 409)
        return jsonify(id=row.id, state='proved')
    if not binding or binding.expires_at <= now():
        binding = NetworkSession(device_id=device.id, user_id=user.id, boot_id=router.boot_id,
            epoch=device.epoch, expires_at=now()+timedelta(hours=8), method='codingprojects_portal', created_by=user.id)
        db.session.add(binding); db.session.flush()
    if user.role == 'student' and not db.session.get(StudentRoom, (router.room_id, user.id)):
        # Physical, authenticated presence makes the pupil visible to this room's teacher.
        db.session.add(StudentRoom(room_id=router.room_id, user_id=user.id))
    row.session_id, row.completed_at = binding.id, now()
    router.desired_revision += 1
    audit(router.room_id, 'session.portal_authenticated', binding.id,
          {'device_id': device.id, 'user_id': user.id, 'role': user.role}, actor=user)
    db.session.commit()
    return jsonify(id=row.id, state='proved')


@network_login.get('/network-login/<login_id>')
@authenticated()
def status(login_id):
    row = db.session.get(NetworkLogin, login_id)
    if not row or row.user_id != g.user.id:
        raise ApiError('not_found', 404)
    binding = db.session.get(NetworkSession, row.session_id) if row.session_id else None
    router = db.session.get(Router, row.router_id)
    device = db.session.get(Device, binding.device_id) if binding else None
    valid = bool(binding and binding.user_id == g.user.id and not binding.revoked_at and
                 binding.expires_at > now() and active_session(device, router) == binding)
    return jsonify(state='authenticated' if valid else 'pending' if row.expires_at > now() and not row.completed_at else 'expired',
                   device=device_state(device, router) if valid else None, router=router_state(router))
