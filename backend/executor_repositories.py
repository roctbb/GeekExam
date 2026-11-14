"""Capture public GitHub source at a fixed commit on the owning platform."""
from copy import deepcopy
import io
import re
import stat
from urllib.parse import quote, unquote, urlsplit
import zipfile

import requests
from models import db
import executor_transport as transport


def parse_repository(url, ref=None):
    if not isinstance(url, str) or len(url) > 1000: raise ValueError('Invalid repository URL')
    parts = urlsplit(url)
    match = re.fullmatch(r'/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/tree/(.+))?/?', parts.path)
    if (parts.scheme != 'https' or parts.netloc != 'github.com' or parts.query or parts.fragment
            or not match or match[2] in ('.', '..')):
        raise ValueError('Use a public github.com repository URL')
    ref = ref or (unquote(match[3]).rstrip('/') if match[3] else 'HEAD')
    if not isinstance(ref, str) or not 1 <= len(ref) <= 200 or any(ord(c) <= 32 for c in ref):
        raise ValueError('Invalid repository ref')
    return dict(provider='github', url=f'https://github.com/{match[1]}/{match[2]}', owner=match[1], repository=match[2], ref=ref)


def fetch(url, **options):
    response = requests.get(url, timeout=(3, 60), allow_redirects=False,
                            headers={'User-Agent': 'GeekExam-Submission', 'Accept': 'application/vnd.github+json'}, **options)
    response.raise_for_status()
    return response


def capture(run):
    from executor_service import safe_path, validate_files
    snapshot = deepcopy(run.snapshot)
    metadata = snapshot['repository']
    base = f'https://api.github.com/repos/{metadata["owner"]}/{metadata["repository"]}'
    if not metadata.get('commit'):
        if fetch(base).json().get('private', True): raise ValueError('Only public repositories are supported')
        sha = fetch(base + '/commits/' + quote(metadata['ref'], safe='')).json().get('sha')
        if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha): raise ValueError('Invalid commit')
        metadata['commit'] = sha
        run.snapshot = snapshot
        db.session.commit()
    if snapshot.get('files'): return
    archive = fetch(base + '/zipball/' + metadata['commit'])
    target = urlsplit(archive.headers.get('Location', ''))
    if (archive.status_code != 302 or target.scheme != 'https' or target.netloc != 'codeload.github.com'
            or target.fragment or not target.path.startswith(f'/{metadata["owner"]}/{metadata["repository"]}/')):
        raise ValueError('Unexpected GitHub archive origin')
    raw = bytearray()
    with fetch(target.geturl(), stream=True) as response:
        if response.status_code != 200: raise ValueError('Unable to download archive')
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > transport.MAX_FILE: raise ValueError('Repository exceeds 50 MiB')
    files, total, root = [], 0, None
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        if len(source.infolist()) > 10000: raise ValueError('Too many repository entries')
        for item in source.infolist():
            if item.is_dir(): continue
            parts = item.filename.split('/', 1)
            if len(parts) != 2: raise ValueError('Invalid archive root')
            root = root or parts[0]
            if root != parts[0]: raise ValueError('Invalid archive root')
            name = safe_path(parts[1])
            if any(p in ('node_modules', 'vendor', '.venv', 'venv', '__pycache__', '.env') for p in name.split('/')): continue
            if stat.S_ISLNK(item.external_attr >> 16): raise ValueError('Repository symlinks are not supported')
            total += item.file_size
            if total > transport.MAX_FILE or len(files) >= 100: raise ValueError('Repository exceeds limits')
            files.append(dict(name=name, artifact=transport.store(source.read(item))))
    for file in snapshot['task'].get('task_files', []):
        if file.get('kind') != 'starter' or not file.get('read_only'): continue
        existing = next((f for f in files if f['name'] == file['name']), None)
        if existing and existing['artifact']['sha256'] != file['artifact']['sha256']: raise ValueError('Read-only starter was modified')
        if not existing: files.append(dict(name=file['name'], artifact=file['artifact']))
    validate_files(files, snapshot['task']['test_config'])
    metadata['archive'] = transport.store(bytes(raw))
    snapshot['files'] = files
    run.snapshot = snapshot
    db.session.commit()
