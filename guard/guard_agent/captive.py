"""Native Coova-Chilli gates, locally approved for one dedicated pupil bridge."""
import ipaddress
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from .enforcer import local_ipv6_only
from .captive_acl import CaptiveACL
from .lan_radius import LanRadius
from .policy import profile_for, parse_time
from .rci import RciClient, RouterError, has_rci_error


def original_lan_peer(rows, peer, peer_port, local, local_port, network):
    if not isinstance(rows,list):
        raise RouterError('unsupported_nat_table_schema')
    matches = []
    for row in rows:
        if not isinstance(row,dict):
            raise RouterError('unsupported_nat_table_schema')
        # Original and reply tuples must match this very TLS socket. No browser
        # parameters, forwarding headers, IP-only guesses or cached NAT entries.
        if row.get('protocol') not in {'tcp','TCP'}:
            continue
        expected = {'dst':local,'dport':local_port,'src-out':local,
                    'sport-out':local_port,'dst-out':peer,'dport-out':peer_port}
        if any(row.get(k) != v for k,v in expected.items()):
            continue
        try:
            address = ipaddress.IPv4Address(row['src'])
            if address not in network or address in {network.network_address,network.broadcast_address}:
                continue
            if type(row.get('sport')) is not int or not 1 <= row['sport'] <= 65535:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        matches.append(str(address))
    return matches[0] if len(matches) == 1 else None


class CaptiveEnforcer(RciClient):
    def __init__(self, *args, settings, interfaces, router_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.bridge, self.chilli = settings['bridge'], settings['interface']
        if not re.fullmatch(r'Bridge[1-9][0-9]?', self.bridge) or not re.fullmatch(r'Chilli[0-9]', self.chilli) or interfaces != [self.bridge]:
            raise RouterError('dedicated_captive_segment_required')
        listen = ipaddress.IPv4Address(settings['listen'])
        router_ip = ipaddress.IPv4Address(urlsplit(self.base_url).hostname)
        if not listen.is_private or listen.is_loopback or not router_ip.is_private:
            raise RouterError('lan_radius_requires_private_addresses')
        secret_path = Path(settings['radius_secret_file'])
        if secret_path.stat().st_mode & 0o077:
            raise RouterError('radius_secret_file_must_have_mode_0600')
        secret = secret_path.read_text().strip()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{32,128}', secret):
            raise RouterError('invalid_radius_secret')
        self.nas_id, self.listen = settings['nas_id'], str(listen)
        self.router_ip = str(router_ip)
        self.proof_port = settings['proof_port']
        if type(self.proof_port) is not int or not 1024 <= self.proof_port <= 65535:
            raise RouterError('invalid_captive_proof_port')
        self.traffic_acl = CaptiveACL(*args,router_id=router_id,interface=self.chilli,
                                     legacy_acl=settings.get('legacy_acl'),**kwargs)
        self.radius = LanRadius(str(listen), str(router_ip), secret, self.nas_id,
                                settings['auth_port'], settings['acct_port'])
        self.renewed = {}
        self.probed, self.session_cache = {}, (0, [])
        self.radius.start()

    def address_for(self, mac, interface):
        if interface != self.bridge:
            return None
        if time.monotonic()-self.session_cache[0] > .5:
            self.session_cache = (time.monotonic(), self.sessions())
        for row in self.session_cache[1]:
            if row.get('mac','').lower() == mac:
                return row.get('ip')
        if time.monotonic()-self.probed.get(mac,0) >= 3:
            username,password = self.radius.grant(mac,None,None,probe=True)
            self.api('/rci/parse','interface '+self.chilli+' chilli login '+mac+' username '+username+' password '+password)
            self.probed[mac] = time.monotonic()
            # Bound wait for the local NAS response; never grant access to a probe.
            for _ in range(10):
                if self.radius.address(mac):break
                time.sleep(.01)
        return self.radius.address(mac)

    def api(self, path, payload=None):
        allowed = {'/rci/parse', '/rci/show/ipv6/route', '/rci/show/ip/nat', '/rci/interface/'+self.chilli,
                   '/rci/interface/'+self.bridge+'/ip'}
        if path not in allowed:
            raise RouterError('unsupported_captive_endpoint')
        status,_,raw = self._exchange(path,payload)
        if status == 401:
            self.authenticate(); status,_,raw = self._exchange(path,payload)
        if status != 200:
            raise RouterError('captive_http_'+str(status))
        result = json.loads(raw)
        if has_rci_error(result):
            raise RouterError('captive_command_error')
        return result

    def resolve_peer(self, peer, peer_port, local, local_port):
        if peer != urlsplit(self.base_url).hostname or local != self.listen or local_port != self.proof_port:
            return None
        config = self.api('/rci/interface/'+self.chilli)['ip']['address']
        network = ipaddress.IPv4Network(config['address']+'/'+config['mask'],strict=False)
        return original_lan_peer(self.api('/rci/show/ip/nat'),peer,peer_port,local,local_port,network)

    def sessions(self):
        result = self.api('/rci/parse', 'show interface '+self.chilli+' chilli')
        # parse returns the same JSON host table as the native CLI command.
        if not isinstance(result,dict) or not isinstance(result.get('host',[]),list):
            raise RouterError('unsupported_captive_session_schema')
        return result.get('host',[])

    def apply(self, policy, observations, now, *, session_grants=True):
        local_ipv6_only(self.api('/rci/show/ipv6/route'))
        config = self.api('/rci/interface/'+self.chilli)
        chilli = config.get('chilli',{})
        if chilli.get('dhcpif') != self.bridge or chilli.get('radiusnasid') != self.nas_id:
            raise RouterError('captive_local_config_changed')
        desired_garden = {'tcp:'+item['ip']+':'+str(item['port']) for item in policy['resources']}
        desired_garden.add('tcp:'+self.listen+':'+str(self.proof_port))
        garden = set(chilli.get('uamallowed',[]))
        for entry in garden:
            if not re.fullmatch(r'tcp:(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}',entry):
                raise RouterError('foreign_captive_walled_garden')
        for entry in sorted(desired_garden-garden):
            self.api('/rci/parse','interface '+self.chilli+' chilli uamallowed '+entry)
        for entry in sorted(garden-desired_garden):
            self.api('/rci/parse','interface '+self.chilli+' no chilli uamallowed '+entry)
        if desired_garden != set(self.api('/rci/interface/'+self.chilli).get('chilli',{}).get('uamallowed',[])):
            raise RouterError('captive_walled_garden_not_verified')
        # Keenetic transfers the bridge's IPv4 address to Chilli0 when bound.
        bridge_ip = config['ip']['address']
        network = ipaddress.IPv4Network(bridge_ip['address']+'/'+bridge_ip['mask'],strict=False)
        if ipaddress.IPv4Address(self.listen) in network:
            raise RouterError('agent_must_be_outside_student_segment')
        restricted = policy['manual_restriction'] or any(not x['expires_at'] or parse_time(x['expires_at']) > now for x in policy['restrictions'])
        devices = {x['mac']:x for x in policy['devices']}
        wanted,full_addresses = {},[]
        for observed in observations:
            if observed['interface'] != self.bridge or not observed['ip']:
                continue
            if ipaddress.IPv4Address(observed['ip']) not in network:
                raise RouterError('client_outside_student_network')
            device = devices.get(observed['mac'])
            if device:
                profile = profile_for(device,observed,restricted,now,session_grants=session_grants)
                if profile in {'full','platform_only'}:
                    wanted[observed['mac']] = observed
                if profile == 'full':
                    full_addresses.append(observed['ip'])
        # Restrict traffic BEFORE admitting any new native portal session. The
        # native authorization set does not change with the study-mode checkbox.
        self.traffic_acl.apply_traffic(policy['resources'],full_addresses,self.listen,self.router_ip,self.proof_port)
        self.radius.retain({(x['mac'],x['ip'],x['epoch']) for x in wanted.values()})
        current = {x['mac'].lower():x for x in self.sessions()}
        for mac in current.keys()-wanted.keys():
            if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',mac):
                raise RouterError('invalid_captive_mac')
            self.api('/rci/parse','interface '+self.chilli+' chilli logout '+mac)
            self.renewed.pop(mac,None)
        pending = False
        for mac, observed in wanted.items():
            old = current.get(mac)
            if old and old.get('ip') != observed['ip']:
                self.api('/rci/parse','interface '+self.chilli+' chilli logout '+mac)
                old = None
            identity = (observed['ip'],observed['epoch'])
            previous = self.renewed.get(mac)
            if not old or not previous or previous[0] != identity or time.monotonic()-previous[1] >= 15:
                username,password = self.radius.grant(mac,*identity)
                self.api('/rci/parse','interface '+self.chilli+' chilli login '+mac+' username '+username+' password '+password)
                self.renewed[mac] = (identity,time.monotonic())
            pending |= old is None
        after = {x['mac'].lower():x for x in self.sessions()}
        if set(after)-set(wanted):
            raise RouterError('captive_logout_not_verified')
        if pending or set(wanted)-set(after):
            raise RouterError('captive_login_pending')

    def stop(self):
        self.radius.retain(set())
        self.radius.stop()
