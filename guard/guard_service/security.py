from datetime import timedelta, timezone
from functools import wraps
import hashlib
import hmac
import secrets
from urllib.parse import urlencode

import jwt
from flask import Blueprint, current_app, g, jsonify, redirect, request, session

from .models import db, Device, LoginTicket, NetworkSession, Router, User
from .policy import stamp


class ApiError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


def now():
    return current_app.config["NOW"]()


def epoch_seconds():
    return now().replace(tzinfo=timezone.utc).timestamp()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def body(allowed, required=()):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ApiError("invalid_fields")
    return value


def text(value, limit=160, empty=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ApiError("invalid_text")
    value = value.strip()
    if not value and not empty:
        raise ApiError("empty_text")
    return value


def integer(value, low=1, high=2**31-1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ApiError("invalid_integer")
    return value


def authenticated(*roles):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = db.session.get(User, session.get("user_id")) if session.get("user_id") else None
            if not user or user.role_expires_at <= now():
                raise ApiError("login_required", 401)
            if roles and user.role not in roles:
                raise ApiError("forbidden", 403)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                supplied = request.headers.get("X-CSRF-Token", "")
                if not supplied or not hmac.compare_digest(supplied, session.get("csrf", "")):
                    raise ApiError("csrf_required", 403)
            g.user = user
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def machine_user(secret_key, audience):
    secret = current_app.config.get(secret_key)
    token = request.headers.get("Authorization", "")
    if not secret or not token.startswith("Bearer "):
        raise ApiError("unauthorized_service", 401)
    try:
        data = jwt.decode(token[7:], secret, algorithms=["HS256"], audience=audience,
                          options={"require": ["iat", "exp", "aud", "sub"]})
        if data["exp"] - data["iat"] > 60:
            raise ValueError()
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise ApiError("unauthorized_service", 401) from None
    return data


def update_identity(data):
    user_id = integer(data.get("id"))
    name = text(data.get("name"))
    role = data.get("role")
    if role == "novice":
        role = "student"
    if role not in {"teacher", "admin", "student"}:
        raise ApiError("invalid_identity_role")
    user = db.session.get(User, user_id)
    if user is None:
        user = User(id=user_id, name=name, role=role, role_expires_at=now())
        db.session.add(user)
    user.name, user.role = name, role
    user.role_expires_at = now() + timedelta(seconds=current_app.config["ROLE_TTL_SECONDS"])
    router_ids = db.session.execute(db.select(Router.id).join(Device, Device.router_id == Router.id
    ).join(NetworkSession, NetworkSession.device_id == Device.id).where(
        NetworkSession.user_id == user_id, NetworkSession.revoked_at.is_(None))).scalars().all()
    for router_id in set(router_ids):
        db.session.get(Router, router_id).desired_revision += 1
    return user


auth = Blueprint("auth", __name__)


@auth.get("/auth/login")
def login():
    if not current_app.config.get("CP_JWT_SECRET"):
        raise ApiError("sso_not_configured", 503)
    session["login_state"] = secrets.token_urlsafe(32)
    session["login_started"] = epoch_seconds()
    network = request.args.get('network', '')
    if network:
        from .models import LocalProofEndpoint
        endpoint = db.session.get(LocalProofEndpoint, network)
        if not endpoint or not endpoint.enabled:
            raise ApiError('network_login_not_configured', 409)
    session['login_next'] = '/connect/' + network if network else '/'
    callback = current_app.config["PUBLIC_URL"].rstrip("/") + "/auth/callback?" + urlencode({"state": session["login_state"]})
    return redirect(current_app.config["CP_URL"].rstrip("/") + "/insider/jwt?" + urlencode({"redirect_url": callback}))


@auth.get("/auth/callback")
def callback():
    expected = session.pop("login_state", "")
    started = session.pop("login_started", 0)
    supplied = request.args.get("state", "")
    if not expected or not hmac.compare_digest(expected, supplied) or not 0 <= epoch_seconds() - started <= 300:
        raise ApiError("invalid_login_state", 403)
    token = request.args.get("token", "")
    if not token or len(token) > 8192:
        raise ApiError("invalid_login_token", 403)
    try:
        audience = current_app.config.get("CP_JWT_AUDIENCE")
        data = jwt.decode(token, current_app.config["CP_JWT_SECRET"], algorithms=["HS256"],
                          audience=audience, issuer="codingprojects", leeway=5,
                          options={"require": ["iat", "id", "name", "role", "iss", "purpose", "service_origin"], "verify_aud": bool(audience)})
        if data["purpose"] != "service-login" or data["service_origin"] != current_app.config["PUBLIC_URL"].rstrip("/"):
            raise ValueError()
        issued = data["iat"]
        if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not -5 <= epoch_seconds() - issued <= 60:
            raise ValueError()
    except (jwt.PyJWTError, ValueError, TypeError):
        raise ApiError("invalid_login_token", 403) from None
    token_digest = digest(token)
    if db.session.get(LoginTicket, token_digest):
        raise ApiError("login_token_already_used", 403)
    user = update_identity(data)
    db.session.add(LoginTicket(digest=token_digest, expires_at=now() + timedelta(seconds=65)))
    db.session.commit()
    destination = session.get('login_next', '/')
    session.clear()
    session.update(user_id=user.id, csrf=secrets.token_urlsafe(32))
    return redirect(destination)


@auth.get("/api/me")
@authenticated()
def me():
    return jsonify(id=g.user.id, name=g.user.name, role=g.user.role,
                   role_expires_at=stamp(g.user.role_expires_at), csrf_token=session["csrf"],
                   demo=current_app.config.get("DEMO", False))


@auth.post("/auth/logout")
@authenticated()
def logout():
    from .models import NetworkLogin
    from .routes import audit
    login = db.session.get(NetworkLogin, session.get('network_login_id')) if session.get('network_login_id') else None
    binding = db.session.get(NetworkSession, login.session_id) if login and login.user_id == g.user.id and login.session_id else None
    if binding and binding.user_id == g.user.id and not binding.revoked_at:
        binding.revoked_at = now()
        device = db.session.get(Device, binding.device_id)
        router = db.session.get(Router, device.router_id)
        router.desired_revision += 1
        audit(router.room_id, 'session.portal_logged_out', binding.id, actor=g.user)
        db.session.commit()
    session.clear()
    return jsonify(ok=True)
