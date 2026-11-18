#!/usr/bin/env python3
"""Fetch only the dedicated LAN certificate over the operator's existing SSH."""
import argparse
import os
from pathlib import Path
import re
import shlex
import ssl
import subprocess
import tempfile


def atomic(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent,prefix='.lan-tls-')
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(value);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description='Обновить отдельный TLS-сертификат LAN-агента Guard')
    parser.add_argument('--ssh-host',required=True)
    parser.add_argument('--remote-directory',required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+',args.ssh_host) or args.ssh_host.startswith('-'):
        parser.error('Недопустимый SSH alias')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',args.remote_directory) or '..' in args.remote_directory.split('/'):
        parser.error('Нужен абсолютный путь к отдельному сертификату LAN-агента')
    target = args.destination.expanduser();target.mkdir(mode=0o700,parents=True,exist_ok=True)
    files = {}
    try:
        for name in ['fullchain.pem','privkey.pem']:
            result = subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                '-o','ConnectTimeout=8',args.ssh_host,'cat '+shlex.quote(args.remote_directory.rstrip('/')+'/'+name)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
            if not 1 <= len(result.stdout) <= 65536:
                raise ValueError('Invalid certificate file size')
            files[name] = result.stdout
        # A mismatch or partial remote renewal must never replace a working pair.
        with tempfile.TemporaryDirectory(prefix='.lan-tls-check-',dir=target) as directory:
            root = Path(directory)
            for name,value in files.items():atomic(root/name,value)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(root/'fullchain.pem'),str(root/'privkey.pem'))
        if all((target/name).exists() and (target/name).read_bytes()==value for name,value in files.items()):
            for name in files:(target/name).chmod(0o600)
            print('TLS-сертификат LAN-агента актуален.');return 0
        for name,value in files.items():atomic(target/name,value)
        print('TLS-сертификат LAN-агента обновлён. Ключ сохранён локально с правами 0600.')
        return 0
    except (OSError,ValueError,ssl.SSLError,subprocess.SubprocessError):
        print('Не удалось обновить сертификат LAN-агента; предыдущая пара сохранена.')
        return 1


if __name__=='__main__':raise SystemExit(main())
