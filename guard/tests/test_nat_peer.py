import ipaddress

import pytest

from guard_agent.captive import original_lan_peer


def row(**changes):
    return {'protocol':'TCP','src':'10.1.30.2','sport':50321,'dst':'192.168.2.62','dport':18766,
            'src-out':'192.168.2.62','sport-out':18766,'dst-out':'192.168.2.1','dport-out':60123,**changes}


def resolve(rows):
    return original_lan_peer(rows,'192.168.2.1',60123,'192.168.2.62',18766,ipaddress.IPv4Network('10.1.30.0/24'))


def test_router_nat_tuple_selects_one_real_client_among_shared_nat_clients():
    assert resolve([row(src='10.1.30.3',**{'dport-out':60124}),row()])=='10.1.30.2'
    assert resolve([row(),row()]) is None
    assert resolve([row(protocol='tcp')])=='10.1.30.2'


@pytest.mark.parametrize('change',[
    {'dst':'192.168.2.63'}, {'dport':443}, {'src-out':'192.168.2.63'}, {'sport-out':443},
    {'dst-out':'192.168.2.5'}, {'dport-out':60124}, {'protocol':'udp'}, {'src':'192.168.2.139'},
    {'src':'10.1.30.0'}, {'src':'10.1.30.255'}, {'sport':0},
])
def test_no_ip_only_fallback_or_cross_connection_binding(change):
    assert resolve([row(**change)]) is None
