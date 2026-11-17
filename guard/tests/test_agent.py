from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ipaddress
import json

import pytest

from guard_agent.enforcer import Enforcer, bindings, local_ipv6_only, same_rules
from guard_agent.observer import Observer
from guard_agent.policy import compile_rules, profile_for, validate_policy
from guard_agent.rci import RouterError
from guard_agent.transport import GuardClient, private_read, private_write


NOW = datetime.now(timezone.utc)


@pytest.fixture
def policy():
    return {"schema_version":1,"router_id":"router-a","room_id":"409","revision":1,
            "manual_restriction":False,"restrictions":[],"resources":[{"ip":"195.133.49.12","port":443}],
            "segments":[{"id":"student","interface":"Bridge1","purpose":"student"}],
            "devices":[{"id":"device-a","mac":"02:00:00:00:00:01","ip":"192.168.12.20","epoch":"one","segment_id":"student",
                        "choices":[{"profile":"full","when":"unrestricted","requires_session":True,"expires_at":(NOW+timedelta(minutes=10)).isoformat()},
                                   {"profile":"bootstrap","when":"always","requires_session":False,"expires_at":None}]}],
            "unknown_profile":"bootstrap"}


@pytest.fixture
def observed():
    return {"mac":"02:00:00:00:00:01","ip":"192.168.12.20","epoch":"one","interface":"Bridge1"}


def compile_for(policy, records, **kwargs):
    return compile_rules(policy, "Bridge1", "192.168.12.1", ipaddress.IPv4Network("192.168.12.0/24"), records, NOW, **kwargs)


def test_session_grant_requires_current_mac_ip_epoch_and_cloud_freshness(policy, observed):
    device = policy["devices"][0]
    assert profile_for(device, observed, False, NOW) == "full"
    for field, replacement in [("mac","02:00:00:00:00:02"),("ip","192.168.12.21"),("epoch","two")]:
        assert profile_for(device, {**observed,field:replacement}, False, NOW) == "bootstrap"
    assert profile_for(device, observed, False, NOW, session_grants=False) == "bootstrap"
    assert profile_for(device, None, False, NOW) == "bootstrap"
    assert profile_for(device, observed, False, NOW+timedelta(minutes=11)) == "bootstrap"


def test_device_override_is_mac_bound_and_can_follow_reconnection(policy, observed):
    device = policy["devices"][0]
    device["choices"].insert(0, {"profile":"full","when":"always","requires_session":False,"expires_at":None})
    assert profile_for(device, {**observed,"epoch":"two","ip":"192.168.12.50"}, True, NOW, session_grants=False) == "full"
    assert profile_for(device, {**observed,"mac":"02:00:00:00:00:02"}, False, NOW) == "bootstrap"


def test_unknown_and_static_clients_are_covered_by_final_deny(policy, observed):
    rules = compile_for(policy, [observed])
    assert rules[0]["source"] == observed["ip"] and rules[0]["protocol"] == "ip"
    assert rules[-1]["action"] == "deny" and rules[-1]["source-mask"] == "0.0.0.0"
    assert not any(row["action"] == "permit" and row["protocol"] == "ip" and row["source"] == "0.0.0.0" for row in rules)
    assert not any(row["protocol"] == "ip" and row["action"] == "permit" for row in compile_for(policy, []))


def test_room_locks_and_expiry_recompile_without_new_revision(policy, observed):
    policy["manual_restriction"] = True
    assert compile_for(policy, [observed])[0]["protocol"] == "tcp"
    policy["manual_restriction"] = False
    policy["restrictions"] = [{"id":"exam-a","expires_at":(NOW+timedelta(seconds=10)).isoformat()}]
    assert compile_for(policy, [observed])[0]["protocol"] == "tcp"
    policy["restrictions"][0]["expires_at"] = (NOW-timedelta(seconds=1)).isoformat()
    assert compile_for(policy, [observed])[0]["protocol"] == "ip"


@pytest.mark.parametrize("change", ["router","interface","resource","port","choice"])
def test_policy_rejects_cross_router_or_command_shaped_values(policy, change):
    if change == "router": policy["router_id"] = "other"
    if change == "interface": policy["segments"][0]["interface"] = "Bridge1; reboot"
    if change == "resource": policy["resources"][0]["ip"] = "195.133.49.12 reboot"
    if change == "port": policy["resources"][0]["port"] = "443 reboot"
    if change == "choice": policy["devices"][0]["choices"][0]["profile"] = "command"
    with pytest.raises(RouterError): validate_policy(policy, "router-a", ["Bridge1"])


def test_compiler_refuses_staff_segment_or_out_of_network_full_grant(policy, observed):
    policy["segments"][0]["purpose"] = "staff"
    with pytest.raises(RouterError): compile_for(policy, [observed])
    policy["segments"][0]["purpose"] = "student"
    policy["devices"][0]["ip"] = observed["ip"] = "192.168.2.54"
    with pytest.raises(RouterError): compile_for(policy, [observed])


class FakeRci:
    def __init__(self):
        self.hosts = [{"mac":"02:00:00:00:00:01","ip":"192.168.12.20","name":"Wi-Fi","interface":{"id":"Bridge1"}},
                      {"mac":"02:00:00:00:00:02","ip":"192.168.12.21","name":"Old lease","active":True,"interface":{"id":"Bridge1"}}]
        self.stations = [{"mac":"02:00:00:00:00:01","ap":"AP1","uptime":100}]

    def read(self, key):
        return {"host":self.hosts} if key == "hotspot" else {"station":self.stations}


def test_observer_uses_association_not_dhcp_and_rotates_on_reconnect():
    rci = FakeRci()
    observer = Observer(rci, ["Bridge1"])
    first = observer.read()
    assert len(first) == 1
    rci.stations[0]["uptime"] = 105
    assert observer.read()[0]["epoch"] == first[0]["epoch"]
    rci.stations[0]["uptime"] = 1
    assert observer.read()[0]["epoch"] != first[0]["epoch"]
    rci.stations = []
    assert observer.read() == []


def test_bad_or_unknown_association_cannot_become_complete_offline_observation():
    rci = FakeRci()
    rci.stations.append({"mac":"02:00:00:00:00:03","uptime":10})
    with pytest.raises(RouterError): Observer(rci, ["Bridge1"]).read()


def test_associated_client_waiting_for_dhcp_has_no_ipv4_and_name_is_sanitized():
    rci = FakeRci()
    rci.hosts[0].update(ip="0.0.0.0",name="Device\x00\nname")
    records = Observer(rci, ["Bridge1"]).read()
    assert len(records) == 1
    assert records[0]["ip"] is None and records[0]["name"] == "Devicename"


def test_external_ipv6_is_rejected_and_rule_readback_checks_order(policy, observed):
    local_ipv6_only({"route6":[{"destination":"fd7c:2a18:4239::/64","interface":"Bridge0"}]})
    with pytest.raises(RouterError): local_ipv6_only({"route6":[{"destination":"::/0","interface":"ISP"}]})
    rows = compile_for(policy, [observed])
    assert same_rules([{**row,"acl":"own","index":"hash"} for row in rows], rows)
    assert not same_rules(list(reversed(rows)), rows)
    assert not same_rules([{**rows[0],"disable":True}]+rows[1:], rows)
    with pytest.raises(RouterError): bindings({"access-group":{"acl":"foreign"}})


def test_transport_requires_https_and_protects_local_credentials(tmp_path):
    with pytest.raises(RouterError): GuardClient("http://guard.geekclass.ru")
    with pytest.raises(RouterError): GuardClient("https://guard.geekclass.ru@evil.example/path")
    GuardClient("http://127.0.0.1:8088")
    path = tmp_path / "agent.json"
    private_write(path, {"token":"opaque-secret"})
    assert private_read(path) == {"token":"opaque-secret"}
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(RouterError): private_read(path)


class RouterSimulator(Enforcer):
    """In-memory RCI contract; no real transport or router credentials."""
    def __init__(self):
        self.interfaces = {"Bridge1"}
        self.prefix = "GUARD_simulator"
        self.management_ip = ipaddress.IPv4Address("192.168.2.54")
        self.attached, self.rows, self.mutations, self.corrupt_readback = [], [], [], False

    def api(self, path, payload=None):
        if payload is not None:
            self.mutations.append((path, deepcopy(payload)))
        if path == "/rci/access-list":
            return list(reversed(self.rows)) if self.corrupt_readback else self.rows.copy()
        if path == "/rci/show/ipv6/route":
            return {"route6":[]}
        if path == "/rci/interface/Bridge1/ip":
            return {"address":{"address":"192.168.12.1","mask":"255.255.255.0"},"access-group":deepcopy(self.attached)}
        if path == "/rci/parse":
            parts = payload.split()
            if len(parts) == 2:
                return {}
            _, name, action, protocol, source, source_mask, *rest = parts
            row = {"acl":name,"action":action,"protocol":protocol,"source":source,"source-mask":source_mask}
            if rest[0] == "port":
                row.update({"source-port":rest[2],"src-port-operator":"eq"})
                rest = rest[3:]
            row.update({"destination":rest[0],"destination-mask":rest[1]})
            if len(rest) > 2:
                row.update({"destination-port":rest[4],"dst-port-operator":"eq"})
            self.rows.append(row)
            return {}
        if path == "/rci/" and "access-list" in payload:
            self.rows = [row for row in self.rows if row["acl"] != payload["access-list"]["acl"]]
            return {}
        if path == "/rci/" and "interface" in payload:
            group = payload["interface"]["Bridge1"]["ip"]["access-group"]
            self.attached = [row for row in self.attached if row["acl"] != group["acl"]] if group.get("no") else [{"acl":group["acl"],"direction":"in"}]
            return {}
        raise AssertionError(path)


def test_driver_switches_own_banks_and_preserves_unrelated_acl(policy, observed):
    driver = RouterSimulator()
    driver.rows = [{"acl":"administrator_rules","action":"deny"}]
    driver.apply(policy, [observed], NOW)
    old = driver.attached[0]["acl"]
    mutations = len(driver.mutations)
    driver.apply(policy, [observed], NOW)
    assert len(driver.mutations) == mutations  # Verified unchanged configuration is not rewritten.
    policy["manual_restriction"] = True
    driver.apply(policy, [observed], NOW)
    assert driver.attached[0]["acl"] != old
    assert not any(row["acl"] == old for row in driver.rows)
    assert driver.rows[0]["acl"] == "administrator_rules"
    driver.release()
    assert driver.attached == [] and driver.rows == [{"acl":"administrator_rules","action":"deny"}]


def test_driver_refuses_foreign_binding_or_management_subnet_before_writes(policy, observed):
    driver = RouterSimulator()
    driver.attached = [{"acl":"administrator_rules","direction":"in"}]
    with pytest.raises(RouterError, match="foreign"): driver.apply(policy, [observed], NOW)
    assert driver.mutations == []
    driver.attached = []
    driver.management_ip = ipaddress.IPv4Address("192.168.12.54")
    with pytest.raises(RouterError, match="outside_student"): driver.apply(policy, [observed], NOW)
    assert driver.mutations == []


def test_readback_mismatch_never_replaces_active_acl(policy, observed):
    driver = RouterSimulator()
    driver.apply(policy, [observed], NOW)
    original = deepcopy(driver.attached)
    policy["manual_restriction"] = True
    driver.corrupt_readback = True
    with pytest.raises(RouterError, match="readback"): driver.apply(policy, [observed], NOW)
    assert driver.attached == original
