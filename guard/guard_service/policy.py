import hashlib
import json
from datetime import datetime, timezone

from .models import (db, Device, DeviceOverride, NetworkSession, PolicySnapshot,
                     Restriction, Room, Segment, StudentRule, User)


def stamp(value):
    return value.isoformat(timespec="milliseconds") + "Z" if value else None


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def room_restricted(room, restrictions, now):
    return room.manual_restriction or any(
        item.released_at is None and (item.expires_at is None or item.expires_at > now)
        for item in restrictions
    )


def resolve_profile(choices, restricted, now):
    for choice in choices:
        if choice.get("expires_at") and parse_time(choice["expires_at"]) <= now:
            continue
        if choice["when"] == "restricted" and not restricted:
            continue
        if choice["when"] == "unrestricted" and restricted:
            continue
        return choice["profile"], choice["reason"]
    return "bootstrap", "Нет действующей сетевой авторизации"


def active_session(device, router):
    return db.session.execute(db.select(NetworkSession).where(
        NetworkSession.device_id == device.id, NetworkSession.revoked_at.is_(None),
        NetworkSession.boot_id == router.boot_id, NetworkSession.epoch == device.epoch,
    ).order_by(NetworkSession.expires_at.desc())).scalars().first()


def choices_for(device, router):
    choices = []
    override = db.session.get(DeviceOverride, device.id)
    if override:
        choices.append({"profile": "full", "when": "always", "expires_at": stamp(override.expires_at),
                        "requires_session": False,
                        "reason": "Исключение устройства: " + override.reason})
    net_session = active_session(device, router)
    if net_session:
        user = db.session.get(User, net_session.user_id)
        valid_until = min(net_session.expires_at, user.role_expires_at)
        if user.role in {"teacher", "admin"}:
            choices.append({"profile": "full", "when": "always", "expires_at": stamp(valid_until),
                            "reason": "Роль " + user.role})
        elif user.role == "student":
            rule = db.session.get(StudentRule, net_session.id)
            if rule:
                choices.append({"profile": rule.profile, "when": "always",
                                "expires_at": stamp(min(valid_until, rule.expires_at)),
                                "reason": "Правило ученика: " + rule.reason})
            choices.extend([
                {"profile": "platform_only", "when": "restricted", "expires_at": stamp(valid_until),
                 "reason": "В кабинете действует ограничение"},
                {"profile": "full", "when": "unrestricted", "expires_at": stamp(valid_until),
                 "reason": "Ученическое ограничение выключено"},
            ])
    choices.append({"profile": "bootstrap", "when": "always", "expires_at": None,
                    "reason": "Нет действующей сетевой авторизации"})
    for choice in choices:
        choice.setdefault("requires_session", choice["profile"] != "bootstrap")
    return choices


def compile_policy(router):
    room = db.session.get(Room, router.room_id)
    restrictions = db.session.execute(db.select(Restriction).where(
        Restriction.room_id == room.id, Restriction.released_at.is_(None))).scalars().all()
    segments = db.session.execute(db.select(Segment).where(Segment.router_id == router.id).order_by(Segment.id)).scalars().all()
    devices = db.session.execute(db.select(Device).where(Device.router_id == router.id).order_by(Device.id)).scalars().all()
    return {
        "schema_version": 1, "router_id": router.id, "room_id": room.id,
        "revision": router.desired_revision,
        "manual_restriction": room.manual_restriction,
        "restrictions": [{"id": item.id, "expires_at": stamp(item.expires_at)} for item in sorted(restrictions, key=lambda r: r.id)],
        "resources": room.resources,
        "segments": [{"id": seg.id, "interface": seg.interface, "purpose": seg.purpose} for seg in segments],
        "devices": [{"id": dev.id, "mac": dev.mac, "ip": dev.ip, "epoch": dev.epoch,
                     "segment_id": dev.segment_id, "choices": choices_for(dev, router)} for dev in devices],
        "unknown_profile": "bootstrap",
    }


def snapshot(router):
    saved = db.session.get(PolicySnapshot, (router.id, router.desired_revision))
    if saved is None:
        document = compile_policy(router)
        saved = PolicySnapshot(router_id=router.id, revision=router.desired_revision,
                               digest=fingerprint(document), document=document)
        db.session.add(saved)
        db.session.flush()
    return saved
