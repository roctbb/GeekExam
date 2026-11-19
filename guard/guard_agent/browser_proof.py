"""Opt-in LAN HTTPS listener. Never accepts an identity/IP supplied by a page."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import ssl
import threading
import time
from urllib.parse import urlsplit

from .rci import RouterError
from .control_tunnel import nat_peers


def validated_settings(value):
    if not isinstance(value, dict):
        raise RouterError('invalid_browser_proof_settings')
    try:
        address = ipaddress.IPv4Address(value['listen'])
        port = value['port']
        origin = urlsplit(value['origin'])
        networks = [ipaddress.IPv4Network(item, strict=True) for item in value['student_subnets']]
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError()
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError()
        if origin.scheme != 'https' or not origin.hostname or origin.port != port or origin.username or origin.password or origin.path not in {'','/'} or origin.query or origin.fragment:
            raise ValueError()
        if not networks or len(networks) > 8 or any(not net.is_private or net.is_loopback or not 16 <= net.prefixlen <= 30 for net in networks):
            raise ValueError()
        allowed = value['allowed_origins']
        if not isinstance(allowed,list) or not allowed or len(allowed)>4:
            raise ValueError()
        for item in allowed:
            parsed = urlsplit(item)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise ValueError()
        key = Path(value['tls_key_file']).expanduser()
        cert = Path(value['tls_cert_file']).expanduser()
        if key.stat().st_mode & 0o077:
            raise RouterError('tls_key_must_have_mode_0600')
        if not cert.is_file():
            raise ValueError()
    except (KeyError,ValueError,TypeError,OSError):
        raise RouterError('invalid_browser_proof_settings') from None
    peers = nat_peers(value.get('nat_peer_ips', []), listen=str(address))
    return {'listen':str(address),'port':port,'origin':value['origin'].rstrip('/'),'host':origin.netloc,
            'networks':networks,'allowed_origins':set(allowed),'cert':str(cert),'key':str(key),
            'nat_peers': peers,
            'diagnostics':value.get('diagnostics') is True}


class LanProofServer:
    def __init__(self, settings, cloud, observe, boot_id, resolve_peer=None):
        self.settings = validated_settings(settings)
        self.cloud, self.observe, self.boot_id = cloud, observe, boot_id
        self.resolve_peer = resolve_peer
        if self.settings.get('nat_peers') and not resolve_peer:
            raise RouterError('nat_peer_resolver_required')
        self.lock, self.recent = threading.Lock(), {}
        self.slots = threading.BoundedSemaphore(4)
        owner = self

        def diagnostic(status, reason=None):
            if owner.settings.get('diagnostics'):
                row = {'status':status}
                if reason:row['reason'] = reason
                print(json.dumps(row),flush=True)

        class Handler(BaseHTTPRequestHandler):
            # Do not log request paths, nonce bodies, certificates or identities.
            def log_message(self, *_args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(12)

            def reply(self, status, data=None):
                raw = b'' if status == 204 else json.dumps(data or {}).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('X-Content-Type-Options','nosniff')
                origin = self.headers.get('Origin')
                if origin in owner.settings['allowed_origins']:
                    self.send_header('Access-Control-Allow-Origin',origin)
                    self.send_header('Vary','Origin')
                if status == 204:
                    self.send_header('Access-Control-Allow-Methods','POST')
                    self.send_header('Access-Control-Allow-Headers','Content-Type')
                    self.send_header('Access-Control-Allow-Private-Network','true')
                    self.send_header('Access-Control-Max-Age','600')
                self.end_headers()
                if status != 204:
                    self.wfile.write(raw)

            def allowed(self):
                return self.path in {'/v1/browser-proof', '/v1/network-login'} and self.headers.get('Host') == owner.settings['host'] and self.headers.get('Origin') in owner.settings['allowed_origins']

            def do_OPTIONS(self):
                if not self.allowed() or self.headers.get('Access-Control-Request-Method') != 'POST':
                    diagnostic('lan_preflight_rejected')
                    self.reply(403);return
                diagnostic('lan_preflight_accepted')
                self.reply(204)

            def do_GET(self):
                diagnostic('lan_listener_reached')
                self.reply(405)

            def do_POST(self):
                if not self.allowed():
                    diagnostic('lan_proof_origin_rejected')
                    self.reply(403);return
                if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    self.reply(400);return
                try:
                    length = int(self.headers.get('Content-Length','0'))
                    if not 1 <= length <= 1024:
                        raise ValueError()
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data,dict) or set(data) != {'token'} or not isinstance(data['token'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',data['token']):
                        raise ValueError()
                    # client_address comes from the TCP socket. Forwarding headers
                    # and JSON parameters can never choose the LAN device.
                    peer = ipaddress.IPv4Address(self.client_address[0])
                    is_nat_peer = str(peer) in owner.settings.get('nat_peers', set())
                    if peer == ipaddress.IPv4Address(owner.settings['listen']) or (not is_nat_peer and not any(peer in net for net in owner.settings['networks'])):
                        diagnostic('lan_proof_peer_rejected')
                        self.reply(403);return
                except (ValueError,TypeError,TimeoutError):
                    self.reply(400);return
                if not owner.slots.acquire(blocking=False):
                    self.reply(429);return
                try:
                    if owner.resolve_peer:
                        original = owner.resolve_peer(str(peer),self.client_address[1],owner.settings['listen'],owner.settings['port'])
                        if is_nat_peer and not original:
                            diagnostic('lan_nat_peer_unresolved')
                            self.reply(403);return
                        if original:
                            peer = ipaddress.IPv4Address(original)
                            if peer == ipaddress.IPv4Address(owner.settings['listen']) or not any(peer in net for net in owner.settings['networks']):
                                self.reply(403);return
                            diagnostic('lan_nat_peer_resolved')
                    # Several pupils share the router's translated address.
                    # Rate limits apply to the verified original peer instead.
                    if not owner.admit(str(peer)):
                        self.reply(429);return
                    context = {'token':data['token'],'origin':self.headers['Origin'],'endpoint_origin':owner.settings['origin']}
                    operation = 'network-login' if self.path == '/v1/network-login' else 'proofs'
                    owner.cloud.post(operation+'/inspect',context)
                    diagnostic('lan_proof_token_accepted')
                    started = time.monotonic()
                    observed = [item for item in owner.observe() if item.get('ip') == str(peer)]
                    if len(observed) != 1:
                        diagnostic('lan_proof_device_not_observed')
                        self.reply(409,{'error':'unique_current_device_required'});return
                    device = observed[0]
                    result = owner.cloud.post(operation+'/complete',{**context,'peer_ip':device['ip'],
                        'mac':device['mac'],'epoch':device['epoch'],'boot_id':owner.boot_id,
                        'source_age_seconds':int(time.monotonic()-started)})
                    diagnostic('lan_proof_completed')
                    self.reply(200,{'id':result['id'],'state':'proved'})
                except RouterError as error:
                    diagnostic('lan_proof_unavailable',getattr(error,'proof_code',str(error)))
                    self.reply(503,{'error':'proof_unavailable'})
                except (OSError,ValueError,KeyError,TypeError):
                    diagnostic('lan_proof_unavailable','local_observation_error')
                    self.reply(503,{'error':'proof_unavailable'})
                finally:
                    owner.slots.release()

        self.server = ThreadingHTTPServer((self.settings['listen'],self.settings['port']),Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.settings['cert'],self.settings['key'])
        self.server.socket = context.wrap_socket(self.server.socket,server_side=True)
        self.cert_stamp = self.certificate_stamp()
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True,name='guard-lan-proof')

    def certificate_stamp(self):
        return tuple(Path(self.settings[key]).stat().st_mtime_ns for key in ['cert','key'])

    def reload_certificates(self):
        stamp = self.certificate_stamp()
        if stamp == self.cert_stamp:
            return
        if Path(self.settings['key']).stat().st_mode & 0o077:
            raise RouterError('tls_key_must_have_mode_0600')
        # Build a complete replacement first; a mismatched refresh leaves the
        # old context intact. Existing requests and agent boot identity survive.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.settings['cert'],self.settings['key'])
        self.server.socket.context = context
        self.cert_stamp = stamp

    def admit(self, peer):
        at = time.monotonic()
        with self.lock:
            self.recent = {key:values for key,values in self.recent.items() if values and values[-1] > at-60}
            if peer not in self.recent and len(self.recent) >= 1024:
                return False
            values = [value for value in self.recent.get(peer,[]) if value > at-60]
            if len(values) >= 12:
                return False
            self.recent[peer] = values+[at]
        return True

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
