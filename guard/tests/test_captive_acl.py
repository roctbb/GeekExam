import ipaddress
from copy import deepcopy

import pytest

from guard_agent.captive_acl import traffic_rules,CaptiveACL
from guard_agent.rci import RouterError
from test_agent import RouterSimulator


def decide(rules,source,destination,protocol='tcp',port=443):
    for row in rules:
        if row['protocol'] not in {'ip',protocol}:continue
        if ipaddress.IPv4Address(source) not in ipaddress.IPv4Network(row['source']+'/'+row['source-mask']):continue
        if ipaddress.IPv4Address(destination) not in ipaddress.IPv4Network(row['destination']+'/'+row['destination-mask']):continue
        if 'destination-port' in row and int(row['destination-port'])!=port:continue
        return row['action']
    return None


def test_limited_access_keeps_platform_and_proof_reachable_without_public_or_management_access():
    rules=traffic_rules([{'ip':'195.133.49.12','port':443}],['10.1.30.2'],'10.1.30.1',
        ipaddress.IPv4Network('10.1.30.0/24'),'192.168.2.62','192.168.2.1',18766)
    assert decide(rules,'10.1.30.2','1.1.1.1')=='permit'
    assert decide(rules,'10.1.30.3','1.1.1.1')=='deny'
    for source in ['10.1.30.2','10.1.30.3','10.1.30.222']:
        assert decide(rules,source,'195.133.49.12')=='permit'
        assert decide(rules,source,'192.168.2.62',port=18766)=='permit'
        assert decide(rules,source,'10.1.30.1',port=3990)=='permit'
        assert decide(rules,source,'192.168.2.1',port=80)=='deny'
        assert decide(rules,source,'192.168.2.62',port=22)=='deny'
        assert decide(rules,source,'10.1.30.1','udp',53)=='permit'


@pytest.mark.parametrize('address',['192.168.2.62','10.1.30.0','10.1.30.1','10.1.30.255'])
def test_full_traffic_grant_must_be_a_current_pupil_address(address):
    with pytest.raises(RouterError):traffic_rules([], [address],'10.1.30.1',ipaddress.IPv4Network('10.1.30.0/24'),'192.168.2.62','192.168.2.1',18766)


class CaptiveSimulator(CaptiveACL,RouterSimulator):
    def __init__(self):
        RouterSimulator.__init__(self)
        self.interface='Chilli0';self.interfaces={'Chilli0'};self.legacy_acl='GUARD_BOOTSTRAP'
        self.attached=[{'acl':self.legacy_acl,'direction':'in'}]
        self.rows=[{'acl':self.legacy_acl,'action':'permit'}, {'acl':'unrelated','action':'deny'}]

    def api(self,path,payload=None):
        if path=='/rci/interface/Chilli0/ip':path='/rci/interface/Bridge1/ip'
        if path=='/rci/' and payload and 'interface' in payload:
            payload=deepcopy(payload)
            payload['interface']['Bridge1']=payload['interface'].pop('Chilli0')
        return RouterSimulator.api(self,path,payload)


def test_bootstrap_is_replaced_by_verified_banks_and_other_lists_are_preserved():
    driver=CaptiveSimulator()
    resources=[{'ip':'195.133.49.12','port':443}]
    driver.apply_traffic(resources,['192.168.12.20'],'192.168.2.62','192.168.2.1',18766)
    first=driver.attached[0]['acl']
    assert first.endswith('_Chilli0_a')
    assert not any(x['acl']=='GUARD_BOOTSTRAP' for x in driver.rows)
    count=len(driver.mutations)
    driver.apply_traffic(resources,['192.168.12.20'],'192.168.2.62','192.168.2.1',18766)
    assert len(driver.mutations)==count
    driver.apply_traffic(resources,[],'192.168.2.62','192.168.2.1',18766)
    assert driver.attached[0]['acl'].endswith('_Chilli0_b')
    assert any(x['acl']=='unrelated' for x in driver.rows)


def test_foreign_binding_or_bad_readback_does_not_replace_the_active_filter():
    driver=CaptiveSimulator();driver.attached=[{'acl':'unrelated','direction':'in'}]
    with pytest.raises(RouterError):driver.apply_traffic([],[],'192.168.2.62','192.168.2.1',18766)
    assert driver.mutations==[]
    driver=CaptiveSimulator();driver.corrupt_readback=True
    with pytest.raises(RouterError):driver.apply_traffic([],[],'192.168.2.62','192.168.2.1',18766)
    assert driver.attached==[{'acl':'GUARD_BOOTSTRAP','direction':'in'}]
