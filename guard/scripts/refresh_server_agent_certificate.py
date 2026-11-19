#!/usr/bin/python3
"""Certbot deploy hook for private Guard listeners on this same server."""
import os
from pathlib import Path
import ssl
import tempfile
import uuid


LINEAGE = Path('/etc/letsencrypt/live/guard.geekclass.ru')
SECRETS = Path('/etc/geekguard/secrets')


def replace(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.guard-tls-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chown(temporary, 10002, 10002)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main():
    if os.environ.get('RENEWED_LINEAGE') != str(LINEAGE):
        return
    if os.geteuid() != 0:
        raise SystemExit('root_required_for_certificate_refresh')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(LINEAGE/'fullchain.pem'), str(LINEAGE/'privkey.pem'))
    files = {name: (LINEAGE/name).read_bytes() for name in ('fullchain.pem', 'privkey.pem')}
    if not SECRETS.exists(): return
    for router in SECRETS.iterdir():
        try: uuid.UUID(router.name)
        except ValueError: continue
        destination = router/'tls'
        # This tree is root-owned and mounted read-only into agents.
        if router.is_symlink() or router.stat().st_uid != 0 or not destination.is_dir() or destination.is_symlink() or destination.stat().st_uid != 0:
            raise SystemExit('unsafe_certificate_destination')
        for name, data in files.items():
            replace(destination/name, data)
    print('Guard agent TLS files refreshed.')


if __name__ == '__main__': main()
