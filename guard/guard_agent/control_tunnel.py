"""Explicit private WireGuard transport for an agent running outside the classroom."""
import ipaddress
import json
import re
import subprocess
import sys
from urllib.parse import urlsplit

from .rci import RouterError


def private_address(value):
    try:
        address = ipaddress.IPv4Address(value)
        if not any(address in ipaddress.IPv4Network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            raise ValueError()
        return str(address)
    except (ValueError, TypeError):
        raise RouterError('private_tunnel_address_required') from None


def nat_peers(values, *, listen=None):
    if not isinstance(values, list) or len(values) > 4:
        raise RouterError('invalid_nat_peer_addresses')
    peers = {private_address(value) for value in values}
    if listen in peers:
        raise RouterError('nat_peer_cannot_be_agent')
    return peers


class ControlTunnel:
    def __init__(self, config):
        settings = config['control_tunnel']
        if not isinstance(settings, dict) or set(settings) != {'interface', 'agent_ip', 'router_ip'}:
            raise RouterError('invalid_control_tunnel_settings')
        self.interface = settings['interface']
        if not isinstance(self.interface, str) or not re.fullmatch(r'wg-[a-z0-9-]{1,12}', self.interface):
            raise RouterError('invalid_control_tunnel_interface')
        self.agent_ip, self.router_ip = private_address(settings['agent_ip']), private_address(settings['router_ip'])
        if self.agent_ip == self.router_ip or urlsplit(config['router_url']).hostname != self.router_ip:
            raise RouterError('control_tunnel_router_mismatch')
        for name in ('captive_portal', 'browser_proof'):
            if config.get(name, {}).get('listen') != self.agent_ip:
                raise RouterError('control_tunnel_listener_mismatch')
        proof_peers = nat_peers(config['browser_proof'].get('nat_peer_ips', []), listen=self.agent_ip)
        captive_peers = nat_peers(config['captive_portal'].get('nat_peer_ips', [self.router_ip]), listen=self.agent_ip)
        if proof_peers != captive_peers or self.router_ip not in proof_peers:
            raise RouterError('control_tunnel_nat_peers_mismatch')

    def read(self, args):
        try:
            result = subprocess.run(['ip', '-j', *args], capture_output=True, timeout=3, check=True)
            if len(result.stdout) > 65536:
                raise ValueError()
            value = json.loads(result.stdout)
            if not isinstance(value, list) or len(value) != 1:
                raise ValueError()
            return value[0]
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            raise RouterError('control_tunnel_unavailable') from None

    def verify(self):
        if sys.platform != 'linux':
            raise RouterError('server_control_tunnel_requires_linux')
        link = self.read(['-d', 'link', 'show', 'dev', self.interface])
        if link.get('linkinfo', {}).get('info_kind') != 'wireguard' or 'UP' not in link.get('flags', []):
            raise RouterError('control_tunnel_not_wireguard_or_down')
        addresses = self.read(['address', 'show', 'dev', self.interface]).get('addr_info', [])
        if not any(row.get('family') == 'inet' and row.get('local') == self.agent_ip for row in addresses):
            raise RouterError('control_tunnel_address_missing')
        route = self.read(['route', 'get', self.router_ip])
        if route.get('dev') != self.interface or route.get('prefsrc', route.get('src')) != self.agent_ip:
            raise RouterError('router_route_outside_control_tunnel')
