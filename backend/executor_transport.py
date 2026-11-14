"""Signed execution transport and private, content-addressed platform storage."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time

from flask import abort, request
import jwt
import requests
import config

MAX_FILE = 50 * 1024 * 1024


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def key():
    if len(config.GEEKEXECUTOR_SECRET) < 32:
        raise ValueError('GEEKEXECUTOR_SECRET must contain at least 32 characters')
    return config.GEEKEXECUTOR_SECRET


def issue(purpose, audience='geekexecutor', ttl=60, **claims):
    now = int(time.time())
    return jwt.encode(dict(claims, iss='geekexam', aud=audience, purpose=purpose, iat=now, exp=now + ttl), key(), algorithm='HS256')


def verify(purpose, body=True):
    try:
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        claims = jwt.decode(token, key(), algorithms=['HS256'], audience='geekexam', issuer='geekexecutor',
                            options={'require': ['iat', 'exp', 'purpose']})
        if (claims['purpose'] != purpose or type(claims['iat']) is not int or type(claims['exp']) is not int
                or not 0 < claims['exp'] - claims['iat'] <= 60):
            raise ValueError
        digest = hashlib.sha256(request.get_data()).hexdigest()
        if body and not hmac.compare_digest(claims.get('body_sha256', ''), digest):
            raise ValueError
        return claims
    except (ValueError, TypeError, KeyError, jwt.PyJWTError):
        abort(401)


def artifact_path(digest):
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid artifact ID')
    return Path(config.EXECUTOR_STORAGE_DIR) / digest[:2] / digest


def store(data):
    if len(data) > MAX_FILE:
        raise ValueError('File exceeds 50 MiB')
    digest = hashlib.sha256(data).hexdigest()
    path = artifact_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as output: output.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    return dict(type='blob', blob_id=digest, sha256=digest, bytes=len(data), truncated=False)


def inline(text):
    raw = text.encode('utf-8')
    if len(raw) <= 65536:
        return dict(type='inline', text=text, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), truncated=False)
    return store(raw)


def artifact_ids(value):
    if isinstance(value, dict):
        if value.get('type') == 'blob': yield value['blob_id']
        else:
            for item in value.values(): yield from artifact_ids(item)
    elif isinstance(value, list):
        for item in value: yield from artifact_ids(item)


def with_urls(value, run_id):
    if isinstance(value, dict):
        if value.get('type') == 'blob':
            token = issue('execution-artifact', 'geekexam', ttl=300, blob_id=value['blob_id'], execution_id=run_id)
            return dict(value, download_url=config.EXECUTOR_CALLBACK_BASE_URL + '/api/executor/artifacts/' + value['blob_id'] + '?token=' + token)
        return {name: with_urls(item, run_id) for name, item in value.items()}
    if isinstance(value, list): return [with_urls(item, run_id) for item in value]
    return value


def dispatch(run):
    body = json_bytes(dict(execution_id=run.id, submission_id=run.submission_id))
    token = issue('code-execution', body_sha256=hashlib.sha256(body).hexdigest())
    response = requests.post(config.GEEKEXECUTOR_URL + '/api/executions', data=body,
                             headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                             timeout=(3, 15), allow_redirects=False)
    response.raise_for_status()
    value = response.json()
    if response.status_code != 202 or value.get('execution_id') != run.id or value.get('accepted') is not True:
        raise ValueError('Executor did not acknowledge this execution')


def subscription(run_id, user_id):
    return dict(url=config.GEEKEXECUTOR_SOCKET_URL, namespace='/executions', event='execution_progress',
                transport='websocket', execution_id=run_id, expires_at=int(time.time()) + 3600,
                token=issue('execution-subscribe', ttl=3600, execution_id=run_id, user_id=user_id))
