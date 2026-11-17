import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from urllib.error import HTTPError, URLError
import ssl

from .rci import NoRedirects, RouterError


def private_write(path, value):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".guard-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_read(path):
    path = Path(path).expanduser()
    if path.stat().st_mode & 0o077:
        raise RouterError("private_file_must_have_mode_0600")
    return json.loads(path.read_text())


class GuardClient:
    def __init__(self, origin, token=None, *, timeout=8):
        parsed = urlsplit(origin)
        local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise RouterError("guard_requires_https_origin")
        self.origin, self.token, self.timeout = origin.rstrip("/"), token, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))

    def post(self, path, body):
        if path not in {"enroll", "sync", "report"}:
            raise RouterError("unsupported_agent_endpoint")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(self.origin + "/api/v1/agent/" + path, data=json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2*1024*1024+1)
                if len(raw) > 2*1024*1024:
                    raise RouterError("guard_response_too_large")
                return json.loads(raw)
        except HTTPError as exc:
            raise RouterError("guard_http_" + str(exc.code)) from None
        except (URLError, OSError, ValueError):
            raise RouterError("guard_network_or_json_error") from None
