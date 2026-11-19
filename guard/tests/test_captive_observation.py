import pytest

from guard_agent.observer import Observer


@pytest.mark.parametrize('current_ip',['10.1.30.3',None])
def test_captive_segment_never_reuses_an_old_trusted_network_dhcp_address(current_ip):
    mac='02:00:00:00:00:01'
    class Source:
        def read(self,kind):
            return {'host':[{'mac':mac,'ip':'192.168.2.139','interface':{'id':'Bridge1'}}]} if kind=='hotspot' else {'station':[{'mac':mac,'uptime':10,'ap':'WifiMaster1/AccessPoint0'}]}
    observer=Observer(Source(),['Bridge0','Bridge1'],address_resolver=lambda _mac,_interface:current_ip)
    observer.address_resolver_interfaces={'Bridge1'}
    assert observer.read()[0]['ip']==current_ip
