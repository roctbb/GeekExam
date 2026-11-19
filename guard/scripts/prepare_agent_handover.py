#!/usr/bin/env python3
"""After stopping the old agent, prepare a one-use identity-only handover."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from guard_agent.__main__ import config_read,password_source
from guard_agent.handover import identity_fingerprint
from guard_agent.observer import uptime
from guard_agent.policy import parse_time
from guard_agent.rci import RciClient,RouterError
from guard_agent.transport import GuardClient,private_write


def prepare(config,destination):
    if config.get('control_tunnel') is not None:
        from guard_agent.control_tunnel import ControlTunnel
        ControlTunnel(config).verify()
    started=time.monotonic()
    cloud=GuardClient(config['guard_url'],config['token'],timeout=4)
    state=cloud.post('handover',{})
    rci=RciClient(config['router_url'],config.get('username','admin'),password_source(config),timeout=4)
    hosts={x['mac'].lower():x for x in rci.read('hotspot')['host']}
    stations=rci.read('associations')['station']
    sampled=time.monotonic()
    # Conservatively reject any association young enough to have restarted
    # since the old agent's final sample. No positive permissions are copied.
    gap=(parse_time(state['server_time'])-parse_time(state['observed_at'])).total_seconds()+sampled-started+2
    if gap>15:
        raise RouterError('handover_source_too_old')
    devices={x['mac']:x for x in state['devices']}
    captive=config.get('captive_portal') or {}
    aliases={captive.get('interface'):captive.get('bridge')}
    previous={}
    for station in stations:
        mac=station['mac'].lower();device=devices.get(mac)
        if not device or mac not in hosts:continue
        interface=hosts[mac].get('interface',{}).get('id')
        interface=aliases.get(interface,interface)
        age=uptime(station.get('uptime'))
        if age<gap or interface!=device['interface']:continue
        previous[mac]={'context':[device['ip'],interface,str(station.get('ap',''))],
                       'age':age,'epoch':device['epoch']}
    private_write(destination,{'schema':1,'identity':identity_fingerprint(config),'boot_id':state['boot_id'],
        'next_sequence':state['next_sequence'],'observed_monotonic':sampled,'previous':previous})
    print('Maintenance handover prepared; continuous associations: '+str(len(previous)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:prepare(config_read(args.config),args.output)
    except (RouterError,OSError,KeyError,ValueError,TypeError) as error:
        print(str(error) if isinstance(error,RouterError) else 'maintenance_handover_failed',file=sys.stderr)
        raise SystemExit(1)
