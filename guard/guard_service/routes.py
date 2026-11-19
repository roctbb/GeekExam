from datetime import timedelta
import ipaddress
import re
import secrets

from flask import Blueprint, current_app, g, jsonify, request

from .models import (db, AuditEvent, Device, DeviceOverride, NetworkSession, Restriction,
                     Room, Router, Segment, StudentRoom, StudentRule, TeacherRoom, User)
from .policy import active_session, choices_for, resolve_profile, room_restricted, stamp
from .security import (ApiError, authenticated, body, digest, integer, machine_user,
                       now, text, update_identity)


api = Blueprint("api", __name__, url_prefix="/api/v1")


def find(model, key):
    item = db.session.get(model, key)
    if item is None:
        raise ApiError("not_found", 404)
    return item


def authorize_room(room_id, user=None):
    user = user or g.user
    room = find(Room, room_id)
    if user.role != "admin" and not (user.role == "teacher" and db.session.get(TeacherRoom, (room_id, user.id))):
        raise ApiError("not_found", 404)
    return room


def device_scope(device_id):
    device = find(Device, device_id)
    router = find(Router, device.router_id)
    authorize_room(router.room_id)
    return device, router


def session_scope(session_id):
    binding = find(NetworkSession, session_id)
    device, router = device_scope(binding.device_id)
    user = find(User, binding.user_id)
    if g.user.role == "teacher" and user.id != g.user.id and (
        user.role != "student" or not db.session.get(StudentRoom, (router.room_id, user.id))
    ):
        raise ApiError("forbidden", 403)
    return binding, device, router, user


def bump_room(room_id):
    for router in db.session.execute(db.select(Router).where(Router.room_id == room_id)).scalars():
        router.desired_revision += 1


def audit(room_id, event, target_id, details=None, actor=None):
    actor = actor or getattr(g, "user", None)
    details = dict(details or {})
    context = {}
    if event.startswith(('session.', 'student.', 'device.')):
        binding = db.session.get(NetworkSession, str(target_id)) if not event.startswith('device.') else None
        device = db.session.get(Device, details.get('device_id') or (binding.device_id if binding else str(target_id)))
        user = db.session.get(User, details.get('user_id') or (binding.user_id if binding else None)) if details.get('user_id') or binding else None
        if device:
            context.update(device=device.name or device.mac, ip=device.ip)
        if user:
            context['user'] = user.name
    elif event.startswith(('router.', 'agent.', 'policy.')):
        router = db.session.get(Router, str(target_id))
        if router:
            context['router'] = router.name
    if context:
        details['context'] = context
    db.session.add(AuditEvent(room_id=room_id, event=event, target_id=str(target_id),
                              actor_id=actor.id if actor else None, details=details, created_at=now()))


def expected_version(item, value, field="version"):
    if integer(value) != getattr(item, field):
        raise ApiError("version_conflict", 409)


def resources(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ApiError("invalid_resources")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"ip", "port"}:
            raise ApiError("invalid_resource")
        try:
            address = ipaddress.IPv4Address(item["ip"])
        except (ValueError, TypeError):
            raise ApiError("invalid_resource_ip") from None
        if not address.is_global:
            raise ApiError("public_resource_ip_required")
        entry = {"ip": str(address), "port": integer(item["port"], 1, 65535)}
        if entry not in result:
            result.append(entry)
    return result


def is_fresh(router):
    return bool(router.last_seen and router.observation_at and not router.source_error
                and (now()-router.last_seen).total_seconds() <= current_app.config["PRESENCE_TTL_SECONDS"]
                and (now()-router.observation_at).total_seconds() <= current_app.config["PRESENCE_TTL_SECONDS"])


def router_state(router):
    awaiting_login = router.mode == 'enforce' and router.apply_error == 'captive_login_pending'
    if not router.token_digest:
        status = "not_enrolled"
    elif not is_fresh(router):
        status = "unknown"
    elif awaiting_login:
        status = "pending"
    elif router.apply_error:
        status = "error"
    elif router.mode != "enforce":
        status = "observe"
    elif router.applied_revision == router.desired_revision:
        status = "applied"
    else:
        status = "pending"
    return {"id": router.id, "room_id": router.room_id, "name": router.name,
            "version": router.config_version, "status": status, "mode": router.mode,
            "model": router.model, "firmware": router.firmware,
            "desired_revision": router.desired_revision, "applied_revision": router.applied_revision,
            "last_seen": stamp(router.last_seen), "applied_at": stamp(router.applied_at),
            "error": (None if awaiting_login else router.apply_error) or router.source_error, "capabilities": router.capabilities,
            "segments": [{"id": seg.id, "name": seg.name, "interface": seg.interface, "purpose": seg.purpose}
                         for seg in db.session.execute(db.select(Segment).where(Segment.router_id == router.id)).scalars()]}


def room_state(room):
    routers = db.session.execute(db.select(Router).where(Router.room_id == room.id).order_by(Router.name)).scalars().all()
    locks = db.session.execute(db.select(Restriction).where(Restriction.room_id == room.id, Restriction.released_at.is_(None))).scalars().all()
    active = [item for item in locks if item.expires_at is None or item.expires_at > now()]
    statuses = [router_state(router) for router in routers]
    applied = sum(item["status"] == "applied" for item in statuses)
    return {"id": room.id, "name": room.name, "description": room.description, "version": room.version,
            "manual_restriction": room.manual_restriction, "restricted": room_restricted(room, locks, now()),
            "resources": room.resources, "router_count": len(routers), "applied_count": applied,
            "status": "empty" if not routers else "applied" if applied == len(routers) else "partial" if applied else "pending",
            "restrictions": [{"id": item.id, "source": item.source, "external_id": item.external_id,
                              "reason": item.reason, "expires_at": stamp(item.expires_at)} for item in active],
            "routers": statuses}


def device_state(device, router=None):
    router = router or find(Router, device.router_id)
    room = find(Room, router.room_id)
    binding = active_session(device, router)
    if binding and binding.expires_at <= now():
        binding = None
    user = db.session.get(User, binding.user_id) if binding else None
    if user and user.role_expires_at <= now():
        user, binding = None, None
    locks = db.session.execute(db.select(Restriction).where(Restriction.room_id == room.id, Restriction.released_at.is_(None))).scalars().all()
    profile, reason = resolve_profile(choices_for(device, router), room_restricted(room, locks, now()), now())
    override = db.session.get(DeviceOverride, device.id)
    individual = db.session.get(StudentRule, binding.id) if binding else None
    return {"id": device.id, "router_id": router.id, "router_name": router.name, "room_id": room.id,
            "segment_id": device.segment_id, "name": device.name, "mac": device.mac, "ip": device.ip,
            "epoch": device.epoch, "presence": "unknown" if not is_fresh(router) else "online" if device.associated else "offline",
            "observed_at": stamp(device.observed_at), "profile": profile, "reason": reason,
            "user": {"id": user.id, "name": user.name, "role": user.role} if user else None,
            "session_id": binding.id if binding else None, "binding_method": binding.method if binding else None,
            "override": {"reason": override.reason, "expires_at": stamp(override.expires_at),
                         "active": override.expires_at is None or override.expires_at > now()} if override else None,
            "student_rule": {"profile": individual.profile, "reason": individual.reason,
                             "expires_at": stamp(individual.expires_at)} if individual else None}


@api.get("/rooms")
@authenticated("teacher", "admin")
def rooms_list():
    query = db.select(Room)
    if g.user.role != "admin":
        query = query.join(TeacherRoom).where(TeacherRoom.user_id == g.user.id)
    return jsonify(items=[room_state(room) for room in db.session.execute(query.order_by(Room.name)).scalars()])


@api.post("/rooms")
@authenticated("admin")
def rooms_create():
    data = body({"name", "description", "resources"}, {"name"})
    room = Room(name=text(data["name"], 100), description=text(data.get("description", ""), 500, True),
                resources=resources(data.get("resources", [{"ip": "195.133.49.12", "port": 443}])))
    db.session.add(room)
    db.session.flush()
    audit(room.id, "room.created", room.id)
    db.session.commit()
    return jsonify(room_state(room)), 201


@api.get("/rooms/<room_id>")
@authenticated("teacher", "admin")
def room_detail(room_id):
    room = authorize_room(room_id)
    result = room_state(room)
    result["devices"] = [device_state(device) for device in db.session.execute(
        db.select(Device).join(Router).where(Router.room_id == room_id).order_by(Device.name)).scalars()]
    result["teacher_ids"] = list(db.session.execute(db.select(TeacherRoom.user_id).where(TeacherRoom.room_id == room_id)).scalars())
    student_ids = db.select(StudentRoom.user_id).where(StudentRoom.room_id == room_id)
    result["students"] = [{"id": u.id, "name": u.name, "role_fresh": u.role_expires_at > now()}
                           for u in db.session.execute(db.select(User).where(User.id.in_(student_ids), User.role == "student").order_by(User.name)).scalars()]
    return jsonify(result)


@api.patch("/rooms/<room_id>")
@authenticated("teacher", "admin")
def room_update(room_id):
    room = authorize_room(room_id)
    data = body({"version", "manual_restriction", "name", "description", "resources"}, {"version"})
    if g.user.role != "admin" and set(data) & {"name", "description", "resources"}:
        raise ApiError("admin_required", 403)
    expected_version(room, data["version"])
    if "manual_restriction" in data:
        if not isinstance(data["manual_restriction"], bool):
            raise ApiError("invalid_restriction")
        room.manual_restriction = data["manual_restriction"]
    for key, limit in (("name", 100), ("description", 500)):
        if key in data:
            setattr(room, key, text(data[key], limit, key == "description"))
    if "resources" in data:
        room.resources = resources(data["resources"])
    # Force a revision even when the submitted value happens to be unchanged.
    room.version += 1
    bump_room(room.id)
    audit(room.id, "room.policy_changed", room.id, {"manual_restriction": room.manual_restriction,
          "changes": sorted(set(data)-{"version"})})
    db.session.commit()
    return jsonify(room_state(room))


@api.put("/rooms/<room_id>/members")
@authenticated("admin")
def room_members(room_id):
    room = authorize_room(room_id)
    data = body({"version", "teacher_ids", "student_ids"}, {"version", "teacher_ids", "student_ids"})
    expected_version(room, data["version"])
    previous = set(db.session.execute(db.select(TeacherRoom.user_id).where(TeacherRoom.room_id == room.id)).scalars())
    previous |= set(db.session.execute(db.select(StudentRoom.user_id).where(StudentRoom.room_id == room.id)).scalars())
    desired = set()
    for key, model, role in (("teacher_ids", TeacherRoom, "teacher"), ("student_ids", StudentRoom, "student")):
        ids = data[key]
        if not isinstance(ids, list) or len(ids) > 500:
            raise ApiError("invalid_member_list")
        ids = set(integer(item) for item in ids)
        for user_id in ids:
            if find(User, user_id).role != role:
                raise ApiError("member_role_mismatch")
        db.session.execute(db.delete(model).where(model.room_id == room.id))
        for user_id in ids:
            db.session.add(model(room_id=room.id, user_id=user_id))
        desired |= ids
    if previous - desired:
        device_ids = db.select(Device.id).join(Router).where(Router.room_id == room.id)
        for binding in db.session.execute(db.select(NetworkSession).where(
            NetworkSession.device_id.in_(device_ids), NetworkSession.user_id.in_(previous-desired), NetworkSession.revoked_at.is_(None))).scalars():
            binding.revoked_at = now()
    room.version += 1
    bump_room(room.id)
    audit(room.id, "room.members_changed", room.id)
    db.session.commit()
    return jsonify(ok=True, version=room.version)


@api.put("/rooms/<room_id>/teachers")
@authenticated("admin")
def room_teachers(room_id):
    room = authorize_room(room_id)
    data = body({"version", "teacher_ids"}, {"version", "teacher_ids"})
    expected_version(room, data["version"])
    if not isinstance(data["teacher_ids"], list) or len(data["teacher_ids"]) > 500:
        raise ApiError("invalid_member_list")
    ids = set(integer(item) for item in data["teacher_ids"])
    if any(find(User, user_id).role != "teacher" for user_id in ids):
        raise ApiError("member_role_mismatch")
    db.session.execute(db.delete(TeacherRoom).where(TeacherRoom.room_id == room.id))
    for user_id in ids:
        db.session.add(TeacherRoom(room_id=room.id, user_id=user_id))
    # Management permissions do not change pupils' automatic membership or Wi-Fi sessions.
    room.version += 1
    audit(room.id, "room.teachers_changed", room.id, {"teacher_ids": sorted(ids)})
    db.session.commit()
    return jsonify(ok=True, version=room.version)


@api.get("/users")
@authenticated("admin")
def users_list():
    return jsonify(items=[{"id": u.id, "name": u.name, "role": u.role, "role_fresh": u.role_expires_at > now()}
                          for u in db.session.execute(db.select(User).order_by(User.name)).scalars()])


@api.post("/routers")
@authenticated("admin")
def router_create():
    data = body({"name", "room_id", "segments"}, {"name", "room_id", "segments"})
    room = authorize_room(data["room_id"])
    items = data["segments"]
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        raise ApiError("invalid_segments")
    router = Router(room_id=room.id, name=text(data["name"], 100))
    db.session.add(router)
    db.session.flush()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", "interface", "purpose"}:
            raise ApiError("invalid_segment")
        interface = text(item["interface"], 40)
        if not re.fullmatch(r"Bridge[0-9]{1,2}", interface) or item["purpose"] not in {"student", "staff", "equipment"}:
            raise ApiError("invalid_segment")
        db.session.add(Segment(router_id=router.id, name=text(item["name"], 100), interface=interface, purpose=item["purpose"]))
    audit(room.id, "router.created", router.id)
    db.session.commit()
    return jsonify(router_state(router)), 201


@api.patch("/routers/<router_id>")
@authenticated("admin")
def router_update(router_id):
    router = find(Router, router_id)
    data = body({"version", "name", "room_id"}, {"version"})
    expected_version(router, data["version"], "config_version")
    old_room = router.room_id
    if "room_id" in data:
        router.room_id = authorize_room(data["room_id"]).id
    if "name" in data:
        router.name = text(data["name"], 100)
    if router.room_id != old_room:
        devices = db.select(Device.id).where(Device.router_id == router.id)
        for binding in db.session.execute(db.select(NetworkSession).where(NetworkSession.device_id.in_(devices), NetworkSession.revoked_at.is_(None))).scalars():
            binding.revoked_at = now()
    router.config_version += 1
    router.desired_revision += 1
    audit(router.room_id, "router.updated", router.id, {"previous_room_id": old_room})
    db.session.commit()
    return jsonify(router_state(router))


@api.post("/routers/<router_id>/enrollment")
@authenticated("admin")
def enrollment_create(router_id):
    router = find(Router, router_id)
    code = secrets.token_urlsafe(32)
    router.enroll_digest = digest(code)
    router.enroll_expires_at = now() + timedelta(minutes=10)
    audit(router.room_id, "agent.enrollment_created", router.id)
    db.session.commit()
    return jsonify(router_id=router.id, code=code, expires_at=stamp(router.enroll_expires_at))


@api.post("/devices/<device_id>/binding")
@authenticated("teacher", "admin")
def bind_device(device_id):
    device, router = device_scope(device_id)
    data = body({"user_id", "epoch", "seconds", "confirmed"}, {"user_id", "epoch", "confirmed"})
    if data["confirmed"] is not True or data["epoch"] != device.epoch or not is_fresh(router) or not device.associated:
        raise ApiError("fresh_device_confirmation_required", 409)
    user = find(User, integer(data["user_id"]))
    if user.role_expires_at <= now():
        raise ApiError("identity_refresh_required", 409)
    if g.user.role != "admin" and user.id != g.user.id and (
        user.role != "student" or not db.session.get(StudentRoom, (router.room_id, user.id))
    ):
        raise ApiError("forbidden", 403)
    for old in db.session.execute(db.select(NetworkSession).where(NetworkSession.device_id == device.id, NetworkSession.revoked_at.is_(None))).scalars():
        old.revoked_at = now()
    binding = NetworkSession(device_id=device.id, user_id=user.id, boot_id=router.boot_id, epoch=device.epoch,
                             expires_at=now()+timedelta(seconds=integer(data.get("seconds", 28800), 60, 28800)), created_by=g.user.id)
    db.session.add(binding)
    router.desired_revision += 1
    db.session.flush()
    audit(router.room_id, "session.manually_confirmed", binding.id, {"device_id": device.id, "user_id": user.id})
    db.session.commit()
    return jsonify(device_state(device, router)), 201


@api.delete("/sessions/<session_id>")
@authenticated("teacher", "admin")
def revoke_binding(session_id):
    binding, _device, router, _user = session_scope(session_id)
    if binding.revoked_at:
        return jsonify(ok=True)
    binding.revoked_at = now()
    router.desired_revision += 1
    audit(router.room_id, "session.revoked", binding.id)
    db.session.commit()
    return jsonify(ok=True)


@api.put("/sessions/<session_id>/access")
@authenticated("teacher", "admin")
def student_access(session_id):
    binding, device, router, user = session_scope(session_id)
    if user.role != "student" or binding.revoked_at or binding.expires_at <= now() or active_session(device, router) != binding:
        raise ApiError("active_student_session_required", 409)
    data = body({"profile", "seconds", "reason"}, {"profile", "seconds", "reason"})
    if data["profile"] not in {"full", "platform_only"}:
        raise ApiError("invalid_profile")
    item = db.session.get(StudentRule, session_id)
    if item is None:
        item = StudentRule(session_id=session_id)
        db.session.add(item)
    item.profile = data["profile"]
    item.expires_at = min(binding.expires_at, now()+timedelta(seconds=integer(data["seconds"], 15, 28800)))
    item.reason, item.created_by = text(data["reason"], 300), g.user.id
    router.desired_revision += 1
    audit(router.room_id, "student.access_changed", binding.id, {"profile": item.profile, "expires_at": stamp(item.expires_at)})
    db.session.commit()
    return jsonify(device_state(device, router))


@api.delete("/sessions/<session_id>/access")
@authenticated("teacher", "admin")
def student_access_delete(session_id):
    binding, device, router, _user = session_scope(session_id)
    item = db.session.get(StudentRule, session_id)
    if item:
        db.session.delete(item)
        router.desired_revision += 1
        audit(router.room_id, "student.access_revoked", binding.id)
    db.session.commit()
    return jsonify(device_state(device, router))


@api.put("/devices/<device_id>/override")
@authenticated("admin")
def override_set(device_id):
    device, router = device_scope(device_id)
    data = body({"reason", "seconds"}, {"reason"})
    item = db.session.get(DeviceOverride, device.id)
    if item is None:
        item = DeviceOverride(device_id=device.id)
        db.session.add(item)
    item.reason, item.created_by = text(data["reason"], 300), g.user.id
    item.expires_at = None if data.get("seconds") is None else now()+timedelta(seconds=integer(data["seconds"], 15, 2592000))
    router.desired_revision += 1
    audit(router.room_id, "device.override_changed", device.id, {"reason": item.reason, "expires_at": stamp(item.expires_at)})
    db.session.commit()
    return jsonify(device_state(device, router))


@api.delete("/devices/<device_id>/override")
@authenticated("admin")
def override_delete(device_id):
    device, router = device_scope(device_id)
    item = db.session.get(DeviceOverride, device.id)
    if item:
        db.session.delete(item)
        router.desired_revision += 1
        audit(router.room_id, "device.override_revoked", device.id)
    db.session.commit()
    return jsonify(device_state(device, router))


@api.get("/rooms/<room_id>/audit")
@authenticated("teacher", "admin")
def audit_list(room_id):
    authorize_room(room_id)
    from .audit_log import audit_page
    return jsonify(audit_page(room_id, request.args))


@api.get("/my-network")
@authenticated()
def my_network():
    device_ids = db.select(NetworkSession.device_id).where(
        NetworkSession.user_id == g.user.id, NetworkSession.revoked_at.is_(None), NetworkSession.expires_at > now())
    items = [device_state(device) for device in db.session.execute(db.select(Device).where(Device.id.in_(device_ids))).scalars()]
    return jsonify(items=[item for item in items if item["user"] and item["user"]["id"] == g.user.id])


@api.post("/internal/identities")
def identities_sync():
    claims = machine_user("CP_SERVICE_SECRET", "guard:identities")
    if claims["sub"] != "codingprojects":
        raise ApiError("unauthorized_service", 401)
    data = body({"users"}, {"users"})
    if not isinstance(data["users"], list) or len(data["users"]) > 500:
        raise ApiError("invalid_user_list")
    for item in data["users"]:
        if not isinstance(item, dict) or set(item) != {"id", "name", "role"}:
            raise ApiError("invalid_identity")
        update_identity(item)
    db.session.commit()
    return jsonify(ok=True, count=len(data["users"]))


def exam_actor(room_id, data):
    claims = machine_user("EXAM_SERVICE_SECRET", "guard:exams")
    if claims["sub"] != "geekexam":
        raise ApiError("unauthorized_service", 401)
    user = find(User, integer(data.get("actor_id")))
    if user.role not in {"teacher", "admin"} or user.role_expires_at <= now():
        raise ApiError("forbidden", 403)
    return authorize_room(room_id, user), user


@api.put("/internal/exams/rooms/<room_id>/restrictions/<external_id>")
def exam_restrict(room_id, external_id):
    data = body({"actor_id", "reason", "seconds"}, {"actor_id", "reason"})
    room, actor = exam_actor(room_id, data)
    external_id = text(external_id, 120)
    item = db.session.execute(db.select(Restriction).where(Restriction.room_id == room.id, Restriction.source == "geekexam", Restriction.external_id == external_id)).scalar_one_or_none()
    if item is None:
        item = Restriction(room_id=room.id, source="geekexam", external_id=external_id)
        db.session.add(item)
    item.reason, item.released_at = text(data["reason"], 300), None
    item.expires_at = None if data.get("seconds") is None else now()+timedelta(seconds=integer(data["seconds"], 60, 604800))
    room.version += 1
    bump_room(room.id)
    db.session.flush()
    audit(room.id, "exam.restriction_set", item.id, {"external_id": external_id}, actor)
    db.session.commit()
    return jsonify(id=item.id, room=room_state(room))


@api.delete("/internal/exams/rooms/<room_id>/restrictions/<external_id>")
def exam_release(room_id, external_id):
    data = body({"actor_id"}, {"actor_id"})
    room, actor = exam_actor(room_id, data)
    item = db.session.execute(db.select(Restriction).where(Restriction.room_id == room.id, Restriction.source == "geekexam", Restriction.external_id == external_id)).scalar_one_or_none()
    if item and item.released_at is None:
        item.released_at = now()
        room.version += 1
        bump_room(room.id)
        audit(room.id, "exam.restriction_released", item.id, actor=actor)
    db.session.commit()
    return jsonify(room_state(room))


@api.post("/internal/presence/query")
def presence_query():
    data = body({"actor_id", "session_ids"}, {"actor_id", "session_ids"})
    claims = machine_user("EXAM_SERVICE_SECRET", "guard:exams")
    if claims["sub"] != "geekexam":
        raise ApiError("unauthorized_service", 401)
    actor = find(User, integer(data["actor_id"]))
    if actor.role not in {"teacher", "admin"} or actor.role_expires_at <= now():
        raise ApiError("forbidden", 403)
    if not isinstance(data["session_ids"], list) or len(data["session_ids"]) > 200:
        raise ApiError("invalid_session_list")
    items = []
    for session_id in data["session_ids"]:
        binding = find(NetworkSession, text(session_id, 36))
        device = find(Device, binding.device_id)
        router = find(Router, device.router_id)
        authorize_room(router.room_id, actor)
        current = active_session(device, router)
        identity = db.session.get(User, binding.user_id)
        valid = bool(current and current.id == binding.id and binding.expires_at > now()
                     and binding.revoked_at is None and identity.role_expires_at > now())
        items.append({"session_id": binding.id, "device_id": device.id, "router_id": router.id,
                      "room_id": router.room_id, "bound": valid,
                      "presence": "unknown" if not valid or not is_fresh(router) else "online" if device.associated else "offline",
                      "observed_at": stamp(device.observed_at)})
    return jsonify(items=items, observed_at=stamp(now()))
