import hashlib
import time

import pytest

pyrad = pytest.importorskip('pyrad')
from pyrad import packet

from guard_agent.lan_radius import LanRadius


@pytest.fixture
def radius():
    instance = LanRadius('127.0.0.1','192.0.2.1','local-test-secret'*4,'room-409',0,0)
    yield instance
    instance.stop()


def request_for(radius, username, password, *, mac='02:00:00:00:00:01', nas='room-409', chap=False):
    request=packet.AuthPacket(code=packet.AccessRequest,secret=radius.secret,dict=radius.dictionary)
    request['User-Name']=username
    request['Calling-Station-Id']=mac
    request['NAS-Identifier']=nas
    if chap:
        request.authenticator=request.CreateAuthenticator()
        # A CHAP identifier above 127 must remain one byte.
        request[3]=[b'\xff'+hashlib.md5(b'\xff'+password.encode()+request.authenticator).digest()]
    else:
        request['User-Password']=request.PwCrypt(password)
    request.add_message_authenticator()
    return request


@pytest.mark.parametrize('chap',[False,True])
def test_only_local_issued_credentials_receive_bounded_authenticated_accept(radius,chap):
    username,password=radius.grant('02:00:00:00:00:01','10.1.30.2','epoch-1')
    req=request_for(radius,username,password,chap=chap)
    raw=radius.response(req.RequestPacket(),'192.0.2.1')
    reply=packet.AuthPacket(packet=raw,secret=radius.secret,dict=radius.dictionary)
    assert req.VerifyReply(reply, rawreply=raw)
    assert reply.verify_message_authenticator(original_authenticator=req.authenticator)
    assert reply.code==packet.AccessAccept
    assert reply['Session-Timeout']==[30]


@pytest.mark.parametrize('change',[{'mac':'02:00:00:00:00:02'},{'nas':'other-room'},{'password':'wrong'}])
def test_reject_wrong_mac_nas_or_password(radius,change):
    username,password=radius.grant('02:00:00:00:00:01','10.1.30.2','epoch-1')
    req=request_for(radius,username,change.get('password',password),**{k:v for k,v in change.items() if k!='password'})
    raw=radius.response(req.RequestPacket(),'192.0.2.1')
    assert packet.AuthPacket(packet=raw,secret=radius.secret,dict=radius.dictionary).code==packet.AccessReject


def test_reject_forgery_expiry_revocation_and_non_router_source(radius):
    username,password=radius.grant('02:00:00:00:00:01','10.1.30.2','epoch-1')
    req=request_for(radius,username,password);raw=req.RequestPacket()
    assert radius.response(raw,'192.0.2.2') is None
    assert radius.response(raw[:-1]+bytes([raw[-1]^1]),'192.0.2.1') is None
    radius.retain(set())
    reply=packet.AuthPacket(packet=radius.response(raw,'192.0.2.1'),secret=radius.secret,dict=radius.dictionary)
    assert reply.code==packet.AccessReject
    username,password=radius.grant('02:00:00:00:00:01','10.1.30.2','epoch-1')
    radius.grants[username]['until']=time.monotonic()-1
    req=request_for(radius,username,password)
    reply=packet.AuthPacket(packet=radius.response(req.RequestPacket(),'192.0.2.1'),secret=radius.secret,dict=radius.dictionary)
    assert reply.code==packet.AccessReject
