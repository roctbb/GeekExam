"""Only current Wi-Fi association evidence is treated as online."""
import ipaddress
import time
import uuid

from .rci import RouterError, normalize_mac


def table(value, key):
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise RouterError("unsupported_" + key + "_schema")
    rows = value[key]
    if any(not isinstance(row, dict) or not normalize_mac(row.get("mac")) for row in rows):
        raise RouterError("invalid_" + key + "_row")
    return rows


def uptime(value):
    if type(value) in {int, float} and value >= 0:
        return float(value)
    if isinstance(value, str):
        try:
            parts = value.split(":")
            if len(parts) == 3:
                return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
            return float(value)
        except ValueError:
            pass
    # Without a reconnection indicator we cannot safely preserve a user grant.
    raise RouterError("unsupported_association_uptime")


class Observer:
    def __init__(self, client, interfaces, aliases=None, address_resolver=None):
        self.client, self.interfaces, self.previous = client, set(interfaces), {}
        self.aliases = aliases or {}
        self.address_resolver = address_resolver
        self.last_complete = None

    def read(self):
        hosts = table(self.client.read("hotspot"), "host")
        stations = table(self.client.read("associations"), "station")
        hosts = {normalize_mac(host["mac"]): host for host in hosts}
        current, records, seen_ips = {}, [], set()
        for station in stations:
            mac = normalize_mac(station["mac"])
            if mac in current:
                raise RouterError("duplicate_wifi_association")
            host = hosts.get(mac)
            if host is None:
                raise RouterError("association_without_network_identity")
            interface = host.get("interface", {})
            if not isinstance(interface, dict) or not isinstance(interface.get("id"), str):
                raise RouterError("unsupported_hotspot_interface")
            interface = interface["id"]
            interface = self.aliases.get(interface, interface)
            if interface not in self.interfaces:
                continue
            address = host.get("ip")
            if interface in self.interfaces and self.address_resolver and address in {None, '', '0.0.0.0'}:
                address = self.address_resolver(mac, interface)
            if address:
                try:
                    parsed = ipaddress.IPv4Address(address)
                except (ValueError, TypeError):
                    raise RouterError("invalid_hotspot_ip") from None
                if parsed.is_multicast or parsed.is_loopback:
                    raise RouterError("invalid_hotspot_ip")
                address = None if parsed.is_unspecified else str(parsed)
                if address and address in seen_ips:
                    raise RouterError("duplicate_active_ip")
                if address:
                    seen_ips.add(address)
            else:
                address = None
            age = uptime(station.get("uptime"))
            previous = self.previous.get(mac)
            # Rotate on reconnect, IP/network/AP change, and after an observation gap.
            context = (address, interface, str(station.get("ap", "")))
            elapsed = time.monotonic() - self.last_complete if self.last_complete is not None else 0
            continuous = previous and previous["context"] == context and age + 2 >= previous["age"] + elapsed
            if self.last_complete is None or time.monotonic() - self.last_complete > 20:
                continuous = False
            epoch = previous["epoch"] if continuous else str(uuid.uuid4())
            current[mac] = {"context": context, "age": age, "epoch": epoch}
            records.append({"mac": mac, "ip": address, "interface": interface, "epoch": epoch,
                            "name": "".join(c for c in str(host.get("name") or host.get("hostname") or "") if ord(c) >= 32)[:160]})
        self.previous, self.last_complete = current, time.monotonic()
        return records
