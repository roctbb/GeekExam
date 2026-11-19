from datetime import datetime, timezone
from unittest.mock import Mock

from guard_agent.captive import CaptiveEnforcer
from guard_agent.rci import RouterError
import pytest


def driver_with_session():
    driver=CaptiveEnforcer.__new__(CaptiveEnforcer)
    driver.bridge,driver.chilli,driver.nas_id,driver.listen='Bridge1','Chilli0','room-409','192.168.2.62'
    driver.proof_port=18766
    driver.radius=Mock();driver.radius.grant.return_value=('temporary-user','temporary-password')
    driver.renewed={}
    sessions=[{'mac':'02:00:00:00:00:01','ip':'10.1.30.2'}]
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


@pytest.mark.parametrize('restricted,fresh,exception,full',[
    (False,True,False,True),(True,True,False,False),(False,False,False,False),(True,False,True,True),
])
def test_native_gate_revokes_student_but_preserves_explicit_device_exception(restricted,fresh,exception,full):
    driver,commands=driver_with_session()
    observed={'mac':'02:00:00:00:00:01','ip':'10.1.30.2','epoch':'current','interface':'Bridge1'}
    choices=([{'profile':'full','when':'always','expires_at':None,'requires_session':False}] if exception else [])
    choices += [{'profile':'full','when':'unrestricted','expires_at':None,'requires_session':True}]
    policy={'manual_restriction':restricted,'restrictions':[],'resources':[{'ip':'195.133.49.12','port':443}],'devices':[{**observed,'choices':choices}]}
    driver.apply(policy,[observed],datetime.now(timezone.utc),session_grants=fresh)
    assert any(' logout ' in x for x in commands) is not full
    assert any(' login ' in x for x in commands) is full
