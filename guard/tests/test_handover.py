import time
import uuid

import pytest

from guard_agent.handover import consume_handover,identity_fingerprint
from guard_agent.observer import Observer
from guard_agent.transport import private_write
from guard_agent.rci import RouterError
from test_agent import FakeRci


def checkpoint(tmp_path,**changes):
    config={'router_id':'router-a','router_url':'http://192.168.2.1','interfaces':['Bridge1'],'student_interfaces':['Bridge1']}
    epoch=str(uuid.uuid4());boot=str(uuid.uuid4())
    value={'schema':1,'identity':identity_fingerprint(config),'boot_id':boot,'next_sequence':105,
        'observed_monotonic':time.monotonic(),'previous':{'02:00:00:00:00:01':{
            'context':['192.168.12.20','Bridge1','AP1'],'age':99,'epoch':epoch}},**changes}
    path=tmp_path/'handover.json';private_write(path,value)
    return config,path,boot,epoch


def test_explicit_handover_preserves_a_continuous_association_and_is_one_use(tmp_path):
    config,path,boot,epoch=checkpoint(tmp_path)
    observer=Observer(FakeRci(),['Bridge1'])
    assert consume_handover(path,config,observer)==(boot,105)
    assert observer.read()[0]['epoch']==epoch
    assert not path.exists()
    assert consume_handover(path,config,observer) is None


def test_real_reconnection_still_rotates_the_epoch_after_handover(tmp_path):
    config,path,_,epoch=checkpoint(tmp_path)
    source=FakeRci();source.stations[0]['uptime']=1
    observer=Observer(source,['Bridge1']);consume_handover(path,config,observer)
    assert observer.read()[0]['epoch']!=epoch


def test_expired_handover_does_not_restore_a_boot_or_any_observation(tmp_path):
    config,path,_,_=checkpoint(tmp_path,observed_monotonic=time.monotonic()-16)
    observer=Observer(FakeRci(),['Bridge1'])
    assert consume_handover(path,config,observer) is None
    assert observer.previous=={}


def test_handover_cannot_cross_router_configuration_or_use_public_permissions(tmp_path):
    config,path,_,_=checkpoint(tmp_path)
    config['router_id']='other-router'
    with pytest.raises(RouterError):consume_handover(path,config,Observer(FakeRci(),['Bridge1']))
