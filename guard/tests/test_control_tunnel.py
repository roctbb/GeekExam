from copy import deepcopy
from unittest.mock import patch

import pytest

from guard_agent.control_tunnel import ControlTunnel, nat_peers
from guard_agent.rci import RouterError


def config():
    return {'router_url': 'http://10.77.4.2',
            'control_tunnel': {'interface': 'wg-guard409', 'agent_ip': '10.77.4.1', 'router_ip': '10.77.4.2'},
            'captive_portal': {'listen': '10.77.4.1', 'nat_peer_ips': ['10.77.4.2']},
            'browser_proof': {'listen': '10.77.4.1', 'nat_peer_ips': ['10.77.4.2']}}


def test_tunnel_requires_matched_private_listeners_router_and_explicit_nat_peers():
    ControlTunnel(config())
    for section, field, value in [('control_tunnel', 'agent_ip', '195.133.49.12'),
                                  ('control_tunnel', 'interface', 'eth0'),
                                  ('control_tunnel', 'router_ip', '10.77.4.9'),
                                  ('browser_proof', 'listen', '0.0.0.0'),
                                  ('browser_proof', 'nat_peer_ips', []),
                                  ('captive_portal', 'nat_peer_ips', ['10.77.4.3'])]:
        changed = deepcopy(config()); changed[section][field] = value
        with pytest.raises(RouterError): ControlTunnel(changed)
    for values in [['0.0.0.0'], ['127.0.0.1'], ['8.8.8.8'], ['10.77.4.1'], '10.77.4.2']:
        with pytest.raises(RouterError): nat_peers(values, listen='10.77.4.1')


def test_route_validation_fails_closed_on_a_wrong_interface_or_missing_address():
    tunnel = ControlTunnel(config())
    good = [{'flags': ['UP'], 'linkinfo': {'info_kind': 'wireguard'}},
            {'addr_info': [{'family': 'inet', 'local': '10.77.4.1'}]},
            {'dev': 'wg-guard409', 'prefsrc': '10.77.4.1'}]
    with patch('guard_agent.control_tunnel.sys.platform', 'linux'), patch.object(tunnel, 'read', side_effect=good):
        tunnel.verify()
    for index, row in [(0, {'flags': ['UP'], 'linkinfo': {'info_kind': 'ether'}}),
                       (0, {'flags': [], 'linkinfo': {'info_kind': 'wireguard'}}),
                       (1, {'addr_info': []}), (2, {'dev': 'eth0', 'prefsrc': '10.77.4.1'}),
                       (2, {'dev': 'wg-guard409', 'prefsrc': '195.133.49.12'})]:
        changed = deepcopy(good); changed[index] = row
        with patch('guard_agent.control_tunnel.sys.platform', 'linux'), patch.object(tunnel, 'read', side_effect=changed):
            with pytest.raises(RouterError): tunnel.verify()
