"""LAN-only RADIUS for short-lived, agent-generated credentials, never CP passwords."""
import hashlib
import hmac
import io
import ipaddress
import secrets
import select
import socket
import threading
import time

from .rci import RouterError, normalize_mac

DICTIONARY = '''
ATTRIBUTE User-Name 1 string
ATTRIBUTE User-Password 2 string
ATTRIBUTE CHAP-Password 3 octets
ATTRIBUTE NAS-IP-Address 4 ipaddr
ATTRIBUTE Framed-IP-Address 8 ipaddr
ATTRIBUTE Session-Timeout 27 integer
ATTRIBUTE Idle-Timeout 28 integer
ATTRIBUTE Calling-Station-Id 31 string
ATTRIBUTE NAS-Identifier 32 string
ATTRIBUTE CHAP-Challenge 60 octets
ATTRIBUTE Message-Authenticator 80 octets
'''


class LanRadius:
    def __init__(self, listen, router_ip, secret, nas_id, auth_port=18120, acct_port=18130):
        from pyrad.dictionary import Dictionary
        self.dictionary = Dictionary(io.StringIO(DICTIONARY))
        self.secret = secret.encode()
        self.router_ip, self.nas_id = router_ip, nas_id
        self.lock, self.grants = threading.Lock(), {}
        self.addresses = {}
        self.stopping = threading.Event()
        self.sockets = []
        try:
            for port in (auth_port, acct_port):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind((listen, port)); self.sockets.append(sock)
        except OSError:
            self.stop(); raise RouterError('lan_radius_bind_failed') from None
        self.thread = threading.Thread(target=self.run, daemon=True, name='guard-lan-radius')

    def grant(self, mac, ip, epoch, *, probe=False):
        with self.lock:
            self.grants = {k:v for k,v in self.grants.items() if v['until'] > time.monotonic()}
            username, password = 'guard-'+secrets.token_hex(12), secrets.token_urlsafe(24)
            self.grants[username] = {'password':password, 'mac':mac, 'ip':ip, 'epoch':epoch, 'until':time.monotonic()+12,'probe':probe}
        return username, password

    def retain(self, allowed):
        with self.lock:
            self.grants = {k:v for k,v in self.grants.items() if (v['probe'] or (v['mac'],v['ip'],v['epoch']) in allowed) and v['until'] > time.monotonic()}

    def address(self, mac):
        with self.lock:
            value = self.addresses.get(mac)
            return value[0] if value and time.monotonic()-value[1] < 8 else None

    def forget_address(self, mac):
        with self.lock:
            self.addresses.pop(mac, None)

    def response(self, raw, source, accounting=False):
        from pyrad import packet
        if source != self.router_ip or not 20 <= len(raw) <= 4096:
            return None
        try:
            if accounting:
                request = packet.AcctPacket(packet=raw, secret=self.secret, dict=self.dictionary)
                if request.code != packet.AccountingRequest or not request.VerifyAcctRequest():
                    return None
                reply = request.CreateReply(); reply.code = packet.AccountingResponse
                return reply.ReplyPacket()
            request = packet.AuthPacket(packet=raw, secret=self.secret, dict=self.dictionary)
            if request.code != packet.AccessRequest:
                return None
            if request.message_authenticator is not None and not request.verify_message_authenticator():
                return None
            with self.lock:
                grant = self.grants.get(request.get('User-Name', [''])[0])
                permitted = bool(grant and grant['until'] > time.monotonic() and
                    request.get('NAS-Identifier') == [self.nas_id] and
                    normalize_mac(request.get('Calling-Station-Id', [''])[0]) == grant['mac'])
                if permitted:
                    if 2 in request:
                        permitted = hmac.compare_digest(request.PwDecrypt(request[2][0]), grant['password'])
                    elif 3 in request:
                        chap = request[3][0]
                        expected = hashlib.md5(chap[:1]+grant['password'].encode()+request.get(60,[request.authenticator])[0]).digest()
                        permitted = len(chap) == 17 and hmac.compare_digest(chap[1:], expected)
                    else:
                        permitted = False
                probe = bool(grant and grant['probe'])
                if permitted and probe:
                    # Keenetic's ordinary hotspot table reports 0.0.0.0 before UAM
                    # login. This NAS-authenticated probe reads its DHCP identity
                    # while ALWAYS rejecting network access.
                    address = ipaddress.IPv4Address(request.get('Framed-IP-Address',['0.0.0.0'])[0])
                    if address.is_private and not address.is_unspecified and not address.is_loopback and not address.is_multicast:
                        self.addresses[grant['mac']] = (str(address),time.monotonic())
                    permitted = False
            reply = request.CreateReply()
            reply.code = packet.AccessAccept if permitted else packet.AccessReject
            if permitted:
                # Router-owned timeout closes access even if the Mac dies.
                reply['Session-Timeout'] = 30
                reply['Idle-Timeout'] = 30
            reply.add_message_authenticator()
            if not probe:
                print('{"status":"lan_radius_accepted"}' if permitted else '{"status":"lan_radius_rejected"}', flush=True)
            return reply.ReplyPacket()
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError, packet.PacketError):
            return None

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stopping.is_set():
            try:
                ready,_,_ = select.select(self.sockets, [], [], .5)
                for sock in ready:
                    raw, address = sock.recvfrom(4097)
                    reply = self.response(raw, address[0], sock is self.sockets[1])
                    if reply:
                        sock.sendto(reply, address)
            except (OSError, ValueError):
                if not self.stopping.is_set():
                    print('{"status":"lan_radius_io_error"}', flush=True)

    def stop(self):
        self.stopping.set()
        for sock in self.sockets:
            sock.close()
