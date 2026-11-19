"""Traffic permissions on the Chilli TUN, independent of portal authentication."""
import ipaddress
import re

from .enforcer import Enforcer
from .policy import rule
from .rci import RouterError


def traffic_rules(resources, full_addresses, gateway, network, listen, router_ip, proof_port):
    rules = [rule('permit','tcp',destination=listen,port=proof_port)]
    for address in dict.fromkeys([gateway,router_ip]):
        rules.extend([rule('permit','udp',destination=address,port=53),
                      rule('permit','tcp',destination=address,port=53)])
    rules.extend([rule('permit','udp',destination=gateway,port=67,source_port=68),
                  rule('permit','udp',destination='255.255.255.255',port=67,source_port=68),
                  rule('permit','tcp',destination=gateway,port=3990)])
    # A full Internet grant never opens the trusted management LAN.
    for destination in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16']:
        block = ipaddress.IPv4Network(destination)
        row = rule('deny','ip',destination=str(block.network_address))
        row['destination-mask'] = str(block.netmask)
        rules.append(row)
    for endpoint in resources:
        rules.append(rule('permit','tcp',destination=endpoint['ip'],port=endpoint['port']))
    for address in sorted(set(full_addresses),key=ipaddress.IPv4Address):
        parsed = ipaddress.IPv4Address(address)
        if parsed not in network or parsed in {network.network_address,network.broadcast_address,ipaddress.IPv4Address(gateway)}:
            raise RouterError('client_outside_student_network')
        rules.append(rule('permit','ip',source=address))
    rules.append(rule('deny','ip'))
    if len(rules)>1100:
        raise RouterError('acl_too_large')
    return rules


class CaptiveACL(Enforcer):
    """Reuse verified two-bank ACL switching, exclusively on the local Chilli."""
    def __init__(self,*args,router_id,interface,legacy_acl=None,**kwargs):
        if not re.fullmatch(r'Chilli[0-9]',interface):
            raise RouterError('invalid_captive_filter_interface')
        if legacy_acl is not None and (not isinstance(legacy_acl,str) or not re.fullmatch(r'GUARD_[A-Za-z0-9_]{1,64}',legacy_acl)):
            raise RouterError('invalid_legacy_captive_acl')
        self.legacy_acl = legacy_acl
        super().__init__(*args,router_id=router_id,interfaces=[interface],**kwargs)
        self.interface = interface

    def names(self,interface):
        names = super().names(interface)
        # Only an explicitly approved local bootstrap list may be replaced.
        if self.legacy_acl and self.legacy_acl not in names:
            names.append(self.legacy_acl)
        return names

    def apply_traffic(self,resources,full_addresses,listen,router_ip,proof_port):
        gateway,network,attached = self.inspect(self.interface)
        rules = traffic_rules(resources,full_addresses,gateway,network,listen,router_ip,proof_port)
        self.install(self.interface,rules,attached)
