from datetime import timedelta
import ipaddress
import secrets

from flask import Blueprint, jsonify, request

from .models import (db, AgentBoot, ApplyReport, Device, NetworkSession,
                     PolicySnapshot, Router, Segment)
from .policy import fingerprint, snapshot, stamp
from .routes import audit,is_fresh
from .security import ApiError, body, digest, integer, now, text


agents = Blueprint("agents", __name__, url_prefix="/api/v1/agent")


def authenticate_agent():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or not 20 <= len(authorization[7:]) <= 150:
        raise ApiError("unauthorized_agent", 401)
    router = db.session.execute(db.select(Router).where(Router.token_digest == digest(authorization[7:])).with_for_update()).scalar_one_or_none()
    if router is None:
        raise ApiError("unauthorized_agent", 401)
    return router


def revoke_router_sessions(router):
    devices = db.select(Device.id).where(Device.router_id == router.id)
    for binding in db.session.execute(db.select(NetworkSession).where(
        NetworkSession.device_id.in_(devices), NetworkSession.revoked_at.is_(None))).scalars():
        binding.revoked_at = now()


@agents.post("/enroll")
def enroll():
    data = body({"code"}, {"code"})
    code = text(data["code"], 100)
    router = db.session.execute(db.select(Router).where(Router.enroll_digest == digest(code))).scalar_one_or_none()
    if router is None or router.enroll_expires_at is None or router.enroll_expires_at <= now():
        raise ApiError("invalid_enrollment", 401)
    if router.boot_id:
        previous = db.session.get(AgentBoot, (router.id, router.boot_id))
        if previous:
            previous.retired = True
    revoke_router_sessions(router)
    token = secrets.token_urlsafe(48)
    router.token_digest = digest(token)
    router.enroll_digest = router.enroll_expires_at = None
    router.boot_id, router.last_sequence, router.last_observation_digest = None, -1, None
    router.last_seen = router.observation_at = router.applied_at = router.applied_revision = None
    router.source_error, router.apply_error, router.mode = None, None, "observe"
    router.desired_revision += 1
    audit(router.room_id, "agent.enrolled", router.id)
    db.session.commit()
    return jsonify(router_id=router.id, token=token), 201


def mac_address(value):
    if not isinstance(value, str):
        raise ApiError("invalid_mac")
    value = value.lower().replace("-", ":")
    parts = value.split(":")
    try:
        valid = len(parts) == 6 and all(len(p) == 2 and 0 <= int(p, 16) <= 255 for p in parts)
    except ValueError:
        valid = False
    if not valid or int(parts[0], 16) & 1:
        raise ApiError("invalid_mac")
    return value


@agents.post('/handover')
def handover_state():
    """Read current observation identities for an explicit LAN-agent upgrade."""
    router=authenticate_agent()
    body(set(),set())
    if not router.boot_id or not is_fresh(router):
        raise ApiError('fresh_observation_required',409)
    segments={s.id:s.interface for s in db.session.execute(db.select(Segment).where(Segment.router_id==router.id)).scalars()}
    devices=db.session.execute(db.select(Device).where(Device.router_id==router.id,Device.associated.is_(True))).scalars().all()
    result={'server_time':stamp(now()),'observed_at':stamp(router.observation_at),'boot_id':router.boot_id,
            'next_sequence':router.last_sequence+1,'devices':[
                {'mac':d.mac,'ip':d.ip,'epoch':d.epoch,'interface':segments[d.segment_id]} for d in devices]}
    db.session.commit()
    return jsonify(result)


@agents.post("/sync")
def sync():
    from .exam_presence import network_event, source_transition
    router = authenticate_agent()
    data = body({"boot_id", "sequence", "complete", "devices", "source_error", "source_age_seconds",
                 "mode", "model", "firmware", "capabilities"},
                {"boot_id", "sequence", "complete", "devices", "mode"})
    boot_id = text(data["boot_id"], 80)
    sequence = integer(data["sequence"], 0)
    if not isinstance(data["complete"], bool) or data["mode"] not in {"observe", "enforce"}:
        raise ApiError("invalid_observation")
    if not isinstance(data["devices"], list) or len(data["devices"]) > 1024:
        raise ApiError("invalid_device_list")
    source_age = integer(data.get("source_age_seconds", 0), 0, 86400)
    from flask import current_app
    usable = source_age <= current_app.config["PRESENCE_TTL_SECONDS"]
    source_error = text(data.get("source_error", ""), 160, True) or None
    if data["complete"] and source_error:
        raise ApiError("inconsistent_observation")
    caps = data.get("capabilities", {})
    if not isinstance(caps, dict) or set(caps) - {"ipv4_filter", "ipv6_filter", "connections_revocation"} or any(not isinstance(v, bool) for v in caps.values()):
        raise ApiError("invalid_capabilities")
    observation_digest = fingerprint(data)
    old_boot = db.session.get(AgentBoot, (router.id, boot_id))
    if old_boot and old_boot.retired:
        raise ApiError("retired_agent_boot", 409)
    if router.boot_id == boot_id and sequence <= router.last_sequence:
        if sequence != router.last_sequence or router.last_observation_digest != observation_digest:
            raise ApiError("observation_sequence_conflict", 409)
        saved = snapshot(router)
        db.session.commit()
        return jsonify(server_time=stamp(now()), policy=saved.document, policy_hash=saved.digest)
    segments = {seg.interface: seg for seg in db.session.execute(db.select(Segment).where(Segment.router_id == router.id)).scalars()}
    records, seen = [], set()
    for item in data["devices"]:
        if not isinstance(item, dict) or set(item) - {"mac", "ip", "name", "epoch", "interface"} or not {"mac", "epoch", "interface"} <= set(item):
            raise ApiError("invalid_device")
        mac = mac_address(item["mac"])
        if mac in seen or item["interface"] not in segments:
            raise ApiError("duplicate_mac_or_unknown_segment")
        seen.add(mac)
        ip = item.get("ip")
        if ip is not None:
            try:
                address = ipaddress.IPv4Address(ip)
            except (ValueError, TypeError):
                raise ApiError("invalid_device_ip") from None
            if address.is_multicast or address.is_unspecified or address.is_loopback:
                raise ApiError("invalid_device_ip")
            ip = str(address)
        records.append((mac, ip, text(item.get("name", ""), 160, True), text(item["epoch"], 100), segments[item["interface"]]))
    ips = [record[1] for record in records if record[1] is not None]
    if len(ips) != len(set(ips)):
        raise ApiError("duplicate_active_ip")
    changed = False
    new_error = source_error or ("stale_observation" if not usable else None if data["complete"] else "incomplete_observation")
    source_transition(router,new_error)
    if router.boot_id != boot_id:
        if router.boot_id:
            network_event(router,"agent_restarted",last_confirmed=router.observation_at)
            db.session.get(AgentBoot, (router.id, router.boot_id)).retired = True
        if old_boot is None:
            db.session.add(AgentBoot(router_id=router.id, boot_id=boot_id))
        revoke_router_sessions(router)
        router.boot_id = boot_id
        router.applied_revision = router.applied_at = None
        changed = True
    known = {dev.mac: dev for dev in db.session.execute(db.select(Device).where(Device.router_id == router.id)).scalars()}
    observed_at = now()-timedelta(seconds=source_age)
    for mac, ip, name, epoch, segment in records if usable else []:
        device = known.get(mac)
        if device is not None and not device.associated:
            previous_binding = db.session.execute(db.select(NetworkSession).where(
                NetworkSession.device_id == device.id).order_by(NetworkSession.expires_at.desc())).scalars().first()
            if previous_binding:
                network_event(router,"device_reconnected",binding=previous_binding,device=device,at=observed_at,
                              reason="association_restored")
        if device is None:
            device = Device(router_id=router.id, segment_id=segment.id, mac=mac, epoch=epoch)
            db.session.add(device)
            changed = True
        elif (device.ip, device.epoch, device.segment_id) != (ip, epoch, segment.id):
            for binding in db.session.execute(db.select(NetworkSession).where(NetworkSession.device_id == device.id, NetworkSession.revoked_at.is_(None))).scalars():
                binding.revoked_at = now()
                network_event(router,"binding_changed",binding=binding,device=device,at=observed_at,
                              last_confirmed=device.observed_at,reason="connection_changed")
            changed = True
        if not device.associated:
            changed = True
        device.ip, device.epoch, device.segment_id = ip, epoch, segment.id
        device.name, device.associated, device.observed_at = name, True, observed_at
    if data["complete"] and usable:
        departed = sum(mac not in seen and device.associated for mac,device in known.items())
        associated = sum(device.associated for device in known.values())
        for mac, device in known.items():
            if mac not in seen and device.associated:
                last_confirmed = device.observed_at
                device.associated, device.observed_at = False, observed_at
                for binding in db.session.execute(db.select(NetworkSession).where(NetworkSession.device_id == device.id, NetworkSession.revoked_at.is_(None))).scalars():
                    binding.revoked_at = now()
                    network_event(router,"device_disconnected",binding=binding,device=device,at=observed_at,
                                  last_confirmed=last_confirmed,batch=f"{boot_id}:{sequence}",
                                  batch_departed=departed,batch_total=associated)
                changed = True
    router.last_seen, router.observation_at = now(), observed_at
    router.source_error = new_error
    router.model = text(data.get("model", router.model), 120, True)
    router.firmware = text(data.get("firmware", router.firmware), 80, True)
    router.capabilities, router.mode = caps, data["mode"]
    router.last_sequence, router.last_observation_digest = sequence, observation_digest
    if changed:
        router.desired_revision += 1
    db.session.flush()
    saved = snapshot(router)
    db.session.commit()
    return jsonify(server_time=stamp(now()), policy=saved.document, policy_hash=saved.digest)


@agents.post("/report")
def report():
    router = authenticate_agent()
    data = body({"id", "boot_id", "revision", "policy_hash", "mode", "verified", "connections_revoked", "error"},
                {"id", "boot_id", "revision", "policy_hash", "mode", "verified", "connections_revoked"})
    report_id = text(data["id"], 36)
    revision = integer(data["revision"])
    if data["boot_id"] != router.boot_id:
        raise ApiError("wrong_agent_boot", 409)
    if data["mode"] not in {"observe", "enforce"} or not isinstance(data["verified"], bool) or not isinstance(data["connections_revoked"], bool):
        raise ApiError("invalid_apply_report")
    if data["verified"] and data["mode"] != "enforce":
        raise ApiError("observation_is_not_enforcement")
    if data["connections_revoked"] and not router.capabilities.get("connections_revocation"):
        raise ApiError("unsupported_revocation_claim")
    saved = db.session.get(PolicySnapshot, (router.id, revision))
    if saved is None or saved.digest != data["policy_hash"]:
        raise ApiError("unknown_policy_snapshot", 409)
    error = text(data.get("error", ""), 300, True) or None
    if error and data["verified"]:
        raise ApiError("inconsistent_apply_report")
    existing = db.session.get(ApplyReport, report_id)
    signature = (router.id, revision, data["mode"], data["verified"], data["connections_revoked"], error)
    if existing:
        previous = (existing.router_id, existing.revision, existing.mode, existing.verified, existing.connections_revoked, existing.error)
        if previous != signature:
            raise ApiError("report_id_conflict", 409)
        return jsonify(ok=True)
    db.session.add(ApplyReport(id=report_id, router_id=router.id, revision=revision, mode=data["mode"],
                               verified=data["verified"], connections_revoked=data["connections_revoked"], error=error))
    if data["verified"] and revision >= (router.applied_revision or 0):
        router.applied_revision, router.applied_at = revision, now()
    if revision == router.desired_revision:
        router.apply_error = error
    audit(router.room_id, "policy.reported", router.id, {"revision": revision, "verified": data["verified"], "mode": data["mode"], "error": error})
    db.session.commit()
    return jsonify(ok=True)
