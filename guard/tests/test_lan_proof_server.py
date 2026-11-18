import ipaddress
import json
import ssl
import subprocess
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, HTTPSHandler, Request

import pytest

from guard_agent.browser_proof import LanProofServer, validated_settings
from guard_agent.rci import RouterError


@pytest.fixture
def tls(tmp_path):
    key,cert=tmp_path/'key.pem',tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
        '-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    return key,cert


def test_production_listener_requires_private_bind_tls_and_explicit_student_subnets(tls):
    key,cert=tls
    config={'listen':'192.168.2.54','port':18766,'origin':'https://lan-409.guard.geekclass.ru:18766',
        'student_subnets':['192.168.2.0/24'],'allowed_origins':['https://exam.geekclass.ru'],
        'tls_cert_file':str(cert),'tls_key_file':str(key)}
    assert validated_settings(config)['listen']=='192.168.2.54'
    for changes in [{'listen':'0.0.0.0'},{'listen':'127.0.0.1'},{'listen':'8.8.8.8'},
                    {'origin':'http://lan.local:18766'},{'student_subnets':['0.0.0.0/0']},
                    {'allowed_origins':['*']}]:
        with pytest.raises(RouterError):validated_settings({**config,**changes})
    key.chmod(0o644)
    with pytest.raises(RouterError,match='tls_key_must'):validated_settings(config)


def test_tls_request_uses_actual_socket_peer_and_rejects_browser_ip_claims(tls):
    key,cert=tls
    calls=[]
    class Cloud:
        def post(self,path,body):calls.append((path,body));return {'id':'proof-one'}
    settings={'listen':'127.0.0.1','port':0,'origin':'https://127.0.0.1','host':'127.0.0.1',
        'networks':[ipaddress.IPv4Network('127.0.0.0/24')],'allowed_origins':{'https://exam.geekclass.ru'},
        'cert':str(cert),'key':str(key)}
    with patch('guard_agent.browser_proof.validated_settings',return_value=settings):
        server=LanProofServer({},Cloud(),lambda:[{'ip':'127.0.0.1','mac':'02:00:00:00:00:01','epoch':'epoch'}],'boot')
    port=server.server.server_address[1]
    server.settings['host']=f'127.0.0.1:{port}';server.settings['origin']=f'https://127.0.0.1:{port}'
    server.start()
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
    url=f'https://127.0.0.1:{port}/v1/browser-proof'
    def request(data,origin='https://exam.geekclass.ru',method=None):
        headers={'Content-Type':'application/json','Origin':origin,'X-Forwarded-For':'192.168.2.200'}
        if method=='OPTIONS':headers['Access-Control-Request-Method']='POST'
        try:
            with opener.open(Request(url,data=json.dumps(data).encode() if method!='OPTIONS' else None,headers=headers,method=method),timeout=5) as response:
                return response.status,response.headers,response.read()
        except HTTPError as error:return error.code,error.headers,error.read()
    try:
        # The agent host (or a same-host reverse proxy) cannot stand in for a pupil.
        assert request({'token':'a'*43})[0]==403
        # The loopback client now represents a separate LAN device in this test.
        server.settings['listen']='192.168.2.54'
        assert request({'token':'a'*43},origin='https://evil.example')[0]==403
        assert request({'token':'a'*43,'peer_ip':'192.168.2.200'})[0]==400
        status,headers,_=request({},method='OPTIONS')
        assert status==204 and headers['Access-Control-Allow-Origin']=='https://exam.geekclass.ru'
        status,_,body=request({'token':'a'*43})
        assert status==200 and json.loads(body)['id']=='proof-one'
        assert calls[-1][0]=='proofs/complete'
        assert calls[-1][1]['peer_ip']=='127.0.0.1'
        assert calls[-1][1]['mac']=='02:00:00:00:00:01'
    finally:server.stop()
