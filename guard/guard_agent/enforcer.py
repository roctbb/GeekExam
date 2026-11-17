"""Experimental dedicated-student-bridge ACL adapter.

RCI rule installation is verified by read-back. Existing connection revocation,
IPv6 filtering and a router-resident watchdog are deliberately not claimed.
"""
import hashlib
import ipaddress
import socket
from urllib.parse import urlsplit

from .policy import compile_rules
from .rci import RciClient, RouterError, has_rci_error
import json


def acl_rows(value):
    if value == {}:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) or not isinstance(row.get("acl"), str) for row in value):
        raise RouterError("unsupported_acl_schema")
    return value


def bindings(value):
    if not isinstance(value, dict):
        raise RouterError("unsupported_bridge_schema")
    rows = value.get("access-group", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("acl"), str) or row.get("direction") not in {"in", "out"} for row in rows):
        raise RouterError("unsupported_binding_schema")
    return rows


def local_ipv6_only(value):
    if not isinstance(value, dict) or not isinstance(value.get("route6"), list):
        raise RouterError("unsupported_ipv6_routes")
    for row in value["route6"]:
        try:
            destination = ipaddress.IPv6Network(row["destination"], strict=False)
            if not row["interface"].startswith("Bridge") or not any(destination.subnet_of(ipaddress.IPv6Network(net)) for net in ("fc00::/7", "fe80::/10")):
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise RouterError("external_ipv6_requires_separate_filter") from None


def same_rules(actual, expected):
    keys = {"action", "protocol", "source", "source-mask", "destination", "destination-mask",
            "source-port", "src-port-operator", "destination-port", "dst-port-operator"}
    return len(actual) == len(expected) and all(
        {key: row[key] for key in keys if key in row} == target and
        row.get("disable") in {None, False} and "schedule" not in row for row, target in zip(actual, expected))


class Enforcer(RciClient):
    def __init__(self, *args, router_id, interfaces, **kwargs):
        super().__init__(*args, **kwargs)
        self.interfaces = set(interfaces)
        self.prefix = "GUARD_" + hashlib.sha256(router_id.encode()).hexdigest()[:10]
        try:
            address = ipaddress.ip_address(urlsplit(self.base_url).hostname)
            if not address.is_private or address.is_loopback or address.version != 4:
                raise ValueError()
        except ValueError:
            raise RouterError("router_requires_private_lan_ipv4") from None
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect((str(address), 80))
            self.management_ip = ipaddress.IPv4Address(connection.getsockname()[0])

    def api(self, path, payload=None):
        # All callers below construct finite commands from locally validated values.
        allowed = {"/rci/access-list", "/rci/show/ipv6/route", "/rci/", "/rci/parse"}
        allowed.update("/rci/interface/" + interface + "/ip" for interface in self.interfaces)
        if path not in allowed:
            raise RouterError("unsupported_driver_endpoint")
        status, _, raw = self._exchange(path, payload)
        if status == 401:
            self.authenticate()
            status, _, raw = self._exchange(path, payload)
        if status != 200:
            raise RouterError("rci_http_" + str(status))
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RouterError("rci_invalid_json") from None
        if has_rci_error(result):
            raise RouterError("rci_command_error")
        return result

    def names(self, interface):
        if interface not in self.interfaces:
            raise RouterError("unapproved_student_interface")
        return [self.prefix + "_" + interface + "_" + suffix for suffix in ("a", "b")]

    def binding(self, interface, name, *, remove=False):
        if name not in self.names(interface):
            raise RouterError("foreign_acl_name")
        row = {"acl": name, "direction": "in"}
        if remove:
            row["no"] = True
        return self.api("/rci/", {"interface": {interface: {"ip": {"access-group": row}}}})

    def delete(self, interface, name):
        if name not in self.names(interface):
            raise RouterError("foreign_acl_name")
        return self.api("/rci/", {"access-list": {"acl": name, "no": True}})

    def inspect(self, interface):
        config = self.api("/rci/interface/" + interface + "/ip")
        attached = bindings(config)
        if any(row["acl"] not in self.names(interface) or row["direction"] != "in" for row in attached) or len(attached) > 1:
            raise RouterError("existing_foreign_firewall_binding")
        try:
            gateway = str(ipaddress.IPv4Address(config["address"]["address"]))
            network = ipaddress.IPv4Network(gateway + "/" + config["address"]["mask"], strict=False)
        except (KeyError, ValueError, TypeError):
            raise RouterError("unsupported_student_network") from None
        if self.management_ip in network:
            raise RouterError("agent_must_be_outside_student_segment")
        return gateway, network, attached

    def install(self, interface, rules, attached):
        all_rows = acl_rows(self.api("/rci/access-list"))
        old = attached[0]["acl"] if attached else None
        if old and same_rules([row for row in all_rows if row["acl"] == old], rules):
            return
        target = next(name for name in self.names(interface) if name != old)
        # Delete/rebuild only our inactive bank; the active ACL remains attached.
        if any(row["acl"] == target for row in all_rows):
            self.delete(interface, target)
        self.api("/rci/parse", "access-list " + target)
        for row in rules:
            command = ["access-list", target, row["action"], row["protocol"], row["source"], row["source-mask"]]
            if "source-port" in row:
                command += ["port", "eq", row["source-port"]]
            command += [row["destination"], row["destination-mask"]]
            if "destination-port" in row:
                command += ["port", "eq", row["destination-port"]]
            self.api("/rci/parse", " ".join(command))
        observed = [row for row in acl_rows(self.api("/rci/access-list")) if row["acl"] == target]
        if not same_rules(observed, rules):
            raise RouterError("acl_readback_mismatch")
        # Recheck concurrency before changing the binding.
        if bindings(self.api("/rci/interface/" + interface + "/ip")) != attached:
            raise RouterError("binding_changed_during_apply")
        local_ipv6_only(self.api("/rci/show/ipv6/route"))
        self.binding(interface, target)
        observed_binding = bindings(self.api("/rci/interface/" + interface + "/ip"))
        if old and any(row["acl"] == old for row in observed_binding) and any(row["acl"] == target for row in observed_binding):
            self.binding(interface, old, remove=True)
        if bindings(self.api("/rci/interface/" + interface + "/ip")) != [{"acl": target, "direction": "in"}]:
            raise RouterError("acl_binding_readback_mismatch")
        if old:
            self.delete(interface, old)

    def apply(self, policy, observations, now, *, session_grants=True):
        local_ipv6_only(self.api("/rci/show/ipv6/route"))
        planned = []
        for interface in sorted(self.interfaces):
            gateway, network, attached = self.inspect(interface)
            rules = compile_rules(policy, interface, gateway, network, observations, now, session_grants=session_grants)
            planned.append((interface, rules, attached))
        if not planned:
            raise RouterError("no_student_interfaces_configured")
        for interface, rules, attached in planned:
            self.install(interface, rules, attached)

    def release(self):
        """Explicit local operator action; never called automatically on failure."""
        for interface in sorted(self.interfaces):
            _, _, attached = self.inspect(interface)
            for row in attached:
                self.binding(interface, row["acl"], remove=True)
            for name in self.names(interface):
                if any(row["acl"] == name for row in acl_rows(self.api("/rci/access-list"))):
                    self.delete(interface, name)
            if bindings(self.api("/rci/interface/" + interface + "/ip")):
                raise RouterError("release_verification_failed")
