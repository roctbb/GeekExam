"""Local, finite IPv4 ACL compiler. No CLI fragments are accepted from Guard."""
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re

from .rci import RouterError


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_policy(document, router_id, expected_interfaces):
    try:
        if document["schema_version"] != 1 or document["router_id"] != router_id or document["unknown_profile"] != "bootstrap":
            raise ValueError()
        if not isinstance(document["manual_restriction"], bool) or type(document["revision"]) is not int:
            raise ValueError()
        segments = document["segments"]
        if len({s["id"] for s in segments}) != len(segments) or len({s["interface"] for s in segments}) != len(segments):
            raise ValueError()
        for segment in segments:
            if not re.fullmatch(r"Bridge[0-9]{1,2}", segment["interface"]) or segment["purpose"] not in {"student", "staff", "equipment"}:
                raise ValueError()
        # A cloud-side network change requires local operator confirmation.
        if {s["interface"] for s in segments} != set(expected_interfaces):
            raise ValueError()
        for endpoint in document["resources"]:
            if not ipaddress.IPv4Address(endpoint["ip"]).is_global or type(endpoint["port"]) is not int or not 1 <= endpoint["port"] <= 65535:
                raise ValueError()
        if not 1 <= len(document["resources"]) <= 32:
            raise ValueError()
        for lock in document["restrictions"]:
            if lock["expires_at"]:
                parse_time(lock["expires_at"])
        known_macs = set()
        for device in document["devices"]:
            if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", device["mac"]) or device["mac"] in known_macs:
                raise ValueError()
            known_macs.add(device["mac"])
            if device["ip"] is not None:
                ipaddress.IPv4Address(device["ip"])
            if device["segment_id"] not in {s["id"] for s in segments} or not isinstance(device["epoch"], str):
                raise ValueError()
            for choice in device["choices"]:
                if choice["profile"] not in {"full", "platform_only", "bootstrap"} or choice["when"] not in {"always", "restricted", "unrestricted"} or type(choice["requires_session"]) is not bool:
                    raise ValueError()
                if choice["expires_at"]:
                    parse_time(choice["expires_at"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise RouterError("invalid_or_unapproved_policy") from None
    return document


def profile_for(device, observation, restricted, now, *, session_grants=True):
    if observation is None or observation["mac"] != device["mac"]:
        return "bootstrap"
    same_session = session_grants and (observation["ip"], observation["epoch"]) == (device["ip"], device["epoch"])
    for choice in device["choices"]:
        if choice["requires_session"] and not same_session:
            continue
        if choice["expires_at"] and parse_time(choice["expires_at"]) <= now:
            continue
        if choice["when"] == "restricted" and not restricted or choice["when"] == "unrestricted" and restricted:
            continue
        return choice["profile"]
    return "bootstrap"


def rule(action, protocol, source="0.0.0.0", destination="0.0.0.0", port=None, source_port=None):
    row = {"action": action, "protocol": protocol, "source": source,
           "source-mask": "0.0.0.0" if source == "0.0.0.0" else "255.255.255.255",
           "destination": destination,
           "destination-mask": "0.0.0.0" if destination == "0.0.0.0" else "255.255.255.255"}
    if port is not None:
        row.update({"destination-port": str(port), "dst-port-operator": "eq"})
    if source_port is not None:
        row.update({"source-port": str(source_port), "src-port-operator": "eq"})
    return row


def compile_rules(document, interface, gateway, network, observations, now, *, session_grants=True):
    segment = next(s for s in document["segments"] if s["interface"] == interface)
    if segment["purpose"] != "student":
        raise RouterError("refusing_nonstudent_interface")
    restricted = document["manual_restriction"] or any(
        not lock["expires_at"] or parse_time(lock["expires_at"]) > now for lock in document["restrictions"])
    current = {d["mac"]: d for d in observations if d["interface"] == interface}
    rules = []
    for device in document["devices"]:
        observed = current.get(device["mac"])
        if not observed or device["segment_id"] != segment["id"]:
            continue
        if profile_for(device, observed, restricted, now, session_grants=session_grants) == "full" and observed["ip"]:
            address = ipaddress.IPv4Address(observed["ip"])
            if address not in network or address in {network.network_address, network.broadcast_address, ipaddress.IPv4Address(gateway)}:
                raise RouterError("client_outside_student_network")
            rules.append(rule("permit", "ip", str(address)))
    # Bootstrap and platform_only share the server allowlist in this first release.
    # Crucially this also covers new, unknown and static-IP clients on this bridge.
    for endpoint in document["resources"]:
        rules.append(rule("permit", "tcp", destination=endpoint["ip"], port=endpoint["port"]))
    rules.extend([rule("permit", "udp", destination=gateway, port=53),
                  rule("permit", "tcp", destination=gateway, port=53),
                  rule("permit", "udp", destination=gateway, port=67, source_port=68),
                  rule("permit", "udp", destination="255.255.255.255", port=67, source_port=68),
                  rule("deny", "ip")])
    if len(rules) > 1100:
        raise RouterError("acl_too_large")
    return rules
