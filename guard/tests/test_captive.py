from datetime import datetime, timezone
from unittest.mock import Mock
import time

from guard_agent.captive import CaptiveEnforcer
from guard_agent.rci import RouterError
import pytest


def driver_with_session():
    driver=CaptiveEnforcer.__new__(CaptiveEnforcer)
    driver.bridge,driver.chilli,driver.nas_id,driver.listen='Bridge1','Chilli0','room-409','192.168.2.62'
    driver.proof_port=18766
    driver.guard_https=False
    driver.router_ip='192.168.2.1'
    driver.traffic_acl=Mock()
    driver.radius=Mock();driver.radius.grant.return_value=('temporary-user','temporary-password')
    driver.renewed={'02:00:00:00:00:01':(('10.1.30.2','current'),time.monotonic())}
    sessions=[{'mac':'02:00:00:00:00:01','ip':'10.1.30.2','session-id':'same-native-session'}]
    commands=[]
    def api(path,payload=None):
        if path=='/rci/show/ipv6/route':return {'route6':[]}
        if path=='/rci/interface/Chilli0':return {'chilli':{'dhcpif':'Bridge1','radiusnasid':'room-409','uamallowed':['tcp:195.133.49.12:443','tcp:192.168.2.62:18766']},'ip':{'address':{'address':'10.1.30.1','mask':'255.255.255.0'}}}
        if path=='/rci/interface/Bridge1/ip':return {'address':{'address':'10.1.30.1','mask':'255.255.255.0'}}
        if payload.startswith('show '):return {'host':list(sessions)}
        commands.append(payload)
        if ' logout ' in payload:sessions.clear()
        return {}
    driver.api=api
    return driver,commands


@pytest.mark.parametrize('restricted,fresh,exception,authorized,full',[
    (False,True,False,True,True),(True,True,False,True,False),
    (False,False,False,False,False),(True,False,True,True,True),
])
def test_native_authorization_and_traffic_permission_are_independent(restricted,fresh,exception,authorized,full):
    driver,commands=driver_with_session()
    observed={'mac':'02:00:00:00:00:01','ip':'10.1.30.2','epoch':'current','interface':'Bridge1'}
    choices=([{'profile':'full','when':'always','expires_at':None,'requires_session':False}] if exception else [])
    choices += [{'profile':'full','when':'unrestricted','expires_at':None,'requires_session':True},
                {'profile':'platform_only','when':'restricted','expires_at':None,'requires_session':True}]
    policy={'manual_restriction':restricted,'restrictions':[],'resources':[{'ip':'195.133.49.12','port':443}],'devices':[{**observed,'choices':choices}]}
    driver.apply(policy,[observed],datetime.now(timezone.utc),session_grants=fresh)
    assert any(' logout ' in x for x in commands) is not authorized
    assert not any(' login ' in x for x in commands)
    assert driver.traffic_acl.apply_traffic.call_args.args[1]==(['10.1.30.2'] if full else [])
    retained=driver.radius.retain.call_args.args[0]
    assert bool(retained) is authorized


def test_study_mode_round_trip_preserves_native_session_without_reauthentication():
    driver,commands=driver_with_session()
    observed={'mac':'02:00:00:00:00:01','ip':'10.1.30.2','epoch':'current','interface':'Bridge1'}
    policy={'manual_restriction':False,'restrictions':[],'resources':[{'ip':'195.133.49.12','port':443}],
            'devices':[{**observed,'choices':[
                {'profile':'platform_only','when':'restricted','expires_at':None,'requires_session':True},
                {'profile':'full','when':'unrestricted','expires_at':None,'requires_session':True}]}]}
    for restricted in [False,True,False,True]:
        policy['manual_restriction']=restricted
        driver.apply(policy,[observed],datetime.now(timezone.utc))
        assert driver.sessions()[0]['session-id']=='same-native-session'
    assert commands==[]
    assert [call.args[1] for call in driver.traffic_acl.apply_traffic.call_args_list]==[
        ['10.1.30.2'],[],['10.1.30.2'],[]]
