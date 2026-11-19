"""Explicit, short, one-use maintenance handover; never restore access grants."""
import ipaddress
import math
from pathlib import Path
import time
import uuid

from .policy import fingerprint
from .rci import RouterError,normalize_mac
from .transport import private_read


def identity_fingerprint(config):
    captive=config.get('captive_portal') or {}
    return fingerprint({'router_id':config['router_id'],'router_url':config['router_url'],
        'interfaces':sorted(config['interfaces']),'student_interfaces':sorted(config['student_interfaces']),
        'bridge':captive.get('bridge'),'chilli':captive.get('interface'),'listen':captive.get('listen')})


def consume_handover(path,config,observer):
    path=Path(path)
    if not path.exists():
        return None
    value=private_read(path)
    path.unlink()
    try:
        if value['schema']!=1 or value['identity']!=identity_fingerprint(config):
            raise ValueError()
        saved=value['observed_monotonic']
        if type(saved) not in {int,float} or not math.isfinite(saved):
            raise ValueError()
        if not 0<=time.monotonic()-saved<=15:
            print('{"status":"maintenance_handover_expired"}',flush=True)
            return None
        boot=str(uuid.UUID(value['boot_id']))
        sequence=value['next_sequence']
        if type(sequence) is not int or not 0<=sequence<2**63:
            raise ValueError()
        rows=value['previous']
        if not isinstance(rows,dict) or len(rows)>1024:
            raise ValueError()
        previous={}
        for mac,row in rows.items():
            if normalize_mac(mac)!=mac or int(mac[:2],16)&1:
                raise ValueError()
            context=row['context']
            if not isinstance(context,list) or len(context)!=3 or context[1] not in config['interfaces'] or not isinstance(context[2],str) or len(context[2])>100:
                raise ValueError()
            if context[0] is not None:
                address=ipaddress.IPv4Address(context[0])
                if not address.is_private or address.is_unspecified or address.is_loopback or address.is_multicast:
                    raise ValueError()
            age=row['age']
            if type(age) not in {int,float} or not math.isfinite(age) or age<0:
                raise ValueError()
            epoch=str(uuid.UUID(row['epoch']))
            previous[mac]={'context':tuple(context),'age':age,'epoch':epoch}
        observer.previous,observer.last_complete=previous,saved
    except (ValueError,TypeError,KeyError,AttributeError):
        raise RouterError('invalid_maintenance_handover') from None
    print('{"status":"maintenance_handover_loaded"}',flush=True)
    # Observer.read still checks current IP, AP and continuous association uptime.
    # The run loop obtains a fresh cloud policy before applying any permissions.
    return boot,sequence
