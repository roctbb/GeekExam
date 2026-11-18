"""Authenticated, classroom-scoped evidence for GeekExam. No device control here."""
from datetime import timedelta

from flask import Blueprint, jsonify

from .models import db, AuditEvent, Device, NetworkSession, Room, Router, StudentRoom, TeacherRoom, User
from .policy import active_session, parse_time, stamp
from .routes import authorize_room, is_fresh
from .security import ApiError, body, integer, machine_user, now, text

exam_presence = Blueprint("exam_presence", __name__, url_prefix="/api/v1/internal/exams/network")
KINDS = {"network.device_disconnected", "network.device_reconnected", "network.binding_changed", "network.source_lost",
         "network.source_recovered", "network.agent_restarted"}


def actor(data):
    claims = machine_user("EXAM_SERVICE_SECRET", "guard:exams")
    if claims["sub"] != "geekexam":
        raise ApiError("unauthorized_service", 401)
    user = db.session.get(User, integer(data.get("actor_id")))
    if not user or user.role not in {"teacher", "admin"} or user.role_expires_at <= now():
        raise ApiError("forbidden", 403)
    return user


def network_event(router, kind, *, binding=None, device=None, at=None, last_confirmed=None, **details):
    db.session.add(AuditEvent(room_id=router.room_id, event="network." + kind,
        target_id=binding.id if binding else router.id, created_at=now(), details={
            "router_id":router.id, "device_id":device.id if device else None,
            "session_id":binding.id if binding else None,
            "occurred_at":stamp(at or now()), "last_confirmed_at":stamp(last_confirmed), **details}))


def source_transition(router, error):
    """Record transitions only. An agent error never becomes a client departure."""
    from flask import current_app
    ttl = timedelta(seconds=current_app.config["PRESENCE_TTL_SECONDS"])
    silent = bool(router.last_seen and now() - router.last_seen > ttl)
    latest = db.session.execute(db.select(AuditEvent).where(AuditEvent.target_id == router.id,
        AuditEvent.event.in_(["network.source_lost", "network.source_recovered"])
    ).order_by(AuditEvent.created_at.desc(), db.case((AuditEvent.event == "network.source_recovered",1),else_=0).desc(), AuditEvent.id.desc())).scalars().first()
    lost = latest is not None and latest.event == "network.source_lost"
    if (error or silent) and not lost and router.last_seen:
        since = router.last_seen + ttl if silent else now()
        network_event(router, "source_lost", at=since, last_confirmed=router.observation_at,
                      reason=error or "agent_not_reporting")
    if not error and (lost or silent or router.source_error):
        network_event(router, "source_recovered", last_confirmed=router.observation_at)


def health(router):
    from flask import current_app
    ttl = timedelta(seconds=current_app.config["PRESENCE_TTL_SECONDS"])
    agent_online = bool(router.last_seen and now() - router.last_seen <= ttl)
    fresh = is_fresh(router)
    since = None
    if not fresh and router.last_seen:
        latest = db.session.execute(db.select(AuditEvent).where(AuditEvent.target_id == router.id,
            AuditEvent.event == "network.source_lost").order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())).scalars().first()
        since = latest.details.get("occurred_at") if router.source_error and latest else stamp(router.last_seen + ttl)
    return {"id":router.id, "name":router.name, "fresh":fresh, "agent_online":agent_online,
            "last_contact_at":stamp(router.last_seen), "observed_at":stamp(router.observation_at),
            "unavailable_since":since, "reason":None if fresh else router.source_error or ("agent_not_reporting" if router.last_seen else "never_seen")}


@exam_presence.post("/rooms")
def rooms():
    data = body({"actor_id", "room_id", "user_id"}, {"actor_id"})
    user = actor(data)
    query = db.select(Room).order_by(Room.name)
    if user.role != "admin": query = query.join(TeacherRoom).where(TeacherRoom.user_id == user.id)
    if not data.get("room_id"):
        return jsonify(items=[{"id":r.id,"name":r.name} for r in db.session.execute(query).scalars()])
    room = authorize_room(text(data["room_id"],36), user)
    routers = db.session.execute(db.select(Router).where(Router.room_id == room.id)).scalars().all()
    candidates = []
    if data.get("user_id"):
        student_id = integer(data["user_id"])
        if user.role != "admin" and not db.session.get(StudentRoom,(room.id,student_id)):
            raise ApiError("forbidden",403)
        for binding in db.session.execute(db.select(NetworkSession).join(Device).where(
            NetworkSession.user_id == student_id, NetworkSession.revoked_at.is_(None),
            NetworkSession.expires_at > now(), Device.router_id.in_([r.id for r in routers]))).scalars():
            device = db.session.get(Device,binding.device_id)
            router = db.session.get(Router,device.router_id)
            identity = db.session.get(User,binding.user_id)
            if not is_fresh(router) or not device.associated or not device.ip or identity.role_expires_at <= now() or active_session(device,router) != binding:
                continue
            candidates.append({"session_id":binding.id,"user_id":binding.user_id,"device_id":device.id,
                "router_id":router.id,"device_name":device.name,"router_name":router.name,"ip":device.ip,
                "last_confirmed_at":stamp(device.observed_at),"expires_at":stamp(binding.expires_at)})
    return jsonify(room={"id":room.id,"name":room.name,"routers":[health(r) for r in routers]}, candidates=candidates)


@exam_presence.post("/snapshot")
def snapshot():
    data = body({"actor_id","room_id","session_ids","since"}, {"actor_id","room_id","session_ids","since"})
    user = actor(data)
    room = authorize_room(text(data["room_id"],36),user)
    sessions = data["session_ids"]
    if not isinstance(sessions,list) or len(sessions)>200: raise ApiError("invalid_session_list")
    sessions = list(dict.fromkeys(text(value,36) for value in sessions))
    try: since = parse_time(text(data["since"],40))
    except (ValueError,TypeError): raise ApiError("invalid_since") from None
    if since > now()+timedelta(seconds=5): raise ApiError("invalid_since")
    complete = since >= now()-timedelta(days=7)
    since = max(since,now()-timedelta(days=7))
    routers = db.session.execute(db.select(Router).where(Router.room_id == room.id)).scalars().all()
    router_ids = [r.id for r in routers]
    events = db.session.execute(db.select(AuditEvent).where(AuditEvent.room_id == room.id,
        AuditEvent.event.in_(KINDS), AuditEvent.target_id.in_(sessions+router_ids), AuditEvent.created_at >= since
    ).order_by(AuditEvent.created_at,AuditEvent.id).limit(2001)).scalars().all()
    complete = complete and len(events)<=2000
    events = events[:2000]
    items=[]
    for session_id in sessions:
        binding=db.session.get(NetworkSession,session_id)
        item={"session_id":session_id,"state":"unbound","reason":"unknown_session","since":None,"last_confirmed_at":None}
        if binding:
            device=db.session.get(Device,binding.device_id);router=db.session.get(Router,device.router_id)
            if router.room_id != room.id:
                item["reason"]="room_changed";items.append(item);continue
            item.update(user_id=binding.user_id,device_id=device.id,router_id=router.id,
                        last_confirmed_at=stamp(device.observed_at) if device.associated else None)
            identity=db.session.get(User,binding.user_id)
            if binding.expires_at<=now() or identity.role_expires_at<=now(): item["reason"]="binding_expired"
            elif binding.boot_id != router.boot_id: item["reason"]="agent_restarted"
            elif binding.epoch != device.epoch: item["reason"]="connection_changed"
            elif not is_fresh(router):
                status=health(router);item.update(state="unknown",reason=status["reason"],since=status["unavailable_since"])
            elif binding.revoked_at or not device.associated:
                proof=next((event for event in reversed(events) if event.target_id==session_id and event.event=="network.device_disconnected"),None)
                if proof and not device.associated:
                    item.update(state="offline",reason="device_disconnected",since=proof.details["occurred_at"],
                                last_confirmed_at=proof.details.get("last_confirmed_at"))
                else: item["reason"]="binding_revoked"
            elif active_session(device,router)==binding: item.update(state="online",reason=None)
        items.append(item)
    return jsonify(server_time=stamp(now()),room={"id":room.id,"name":room.name,"routers":[health(r) for r in routers]},
        items=items,history_complete=complete,events=[{"id":e.id,"kind":e.event.removeprefix("network."),
        "detected_at":stamp(e.created_at),**e.details} for e in events])
