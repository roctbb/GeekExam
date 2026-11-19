"""Guard's independent service key stays on the GeekExam backend."""
from datetime import datetime,timezone
from urllib.parse import urlsplit
import jwt
import requests
import config


class GuardUnavailable(Exception):
    def __init__(self,reason):self.reason=reason


def configured(): return bool(config.GUARD_URL and config.GUARD_SERVICE_SECRET)


def call(path,actor_id,**payload):
    if path not in {'rooms','snapshot','proofs/start','proofs/consume'}:raise ValueError('Unsupported Guard operation')
    if not configured():raise GuardUnavailable('not_configured')
    parsed=urlsplit(config.GUARD_URL)
    local=parsed.hostname in {'127.0.0.1','localhost','::1'}
    if (parsed.scheme!='https' and not(local and parsed.scheme=='http')) or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
        raise GuardUnavailable('invalid_guard_origin')
    now=int(datetime.now(timezone.utc).timestamp())
    token=jwt.encode({'sub':'geekexam','aud':'guard:exams','iat':now,'exp':now+30},config.GUARD_SERVICE_SECRET,algorithm='HS256')
    try:
        response=requests.post(config.GUARD_URL.rstrip('/')+'/api/v1/internal/exams/network/'+path,
            json={'actor_id':actor_id,**payload},headers={'Authorization':'Bearer '+token},timeout=(3,5),allow_redirects=False)
        if len(response.content)>2*1024*1024:raise GuardUnavailable('invalid_guard_response')
        if response.status_code == 409 and path == 'proofs/consume':
            raise GuardUnavailable('proof_not_ready')
        if response.status_code == 409 and path == 'proofs/start':
            problem = response.json()
            if isinstance(problem, dict) and problem.get('error') == 'identity_refresh_required':
                raise GuardUnavailable('access_denied')
        if response.status_code!=200:raise GuardUnavailable('access_denied' if response.status_code in (401,403,404) else 'guard_unavailable')
        data=response.json()
        if not isinstance(data,dict):raise ValueError()
        return data
    except (requests.RequestException,ValueError):raise GuardUnavailable('guard_unavailable') from None
