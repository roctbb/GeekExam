#!/usr/bin/env python3
"""Read-only Keenetic LAN RCI probe. Uses only the Python standard library."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import http.client
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request


READ_PATHS = {
    "version": "/rci/show/version",
    "system": "/rci/show/system",
    "hotspot": "/rci/show/ip/hotspot",
    "associations": "/rci/show/associations",
    "interfaces": "/rci/show/interface",
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAC_PATTERN = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z")


class RouterError(Exception):
    """An intentionally redacted error, safe to print without response bodies."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward login material or cookies to another URL.
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_mac(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.lower().replace("-", ":")
    return value if MAC_PATTERN.fullmatch(value) else None


def has_rci_error(value) -> bool:
    if isinstance(value, dict):
        if value.get("status") == "error":
            return True
        return any(has_rci_error(item) for item in value.values())
    if isinstance(value, list):
        return any(has_rci_error(item) for item in value)
    return False


class RciClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: Callable[[], str],
        *,
        timeout: float = 8,
        ca_file: str | None = None,
    ):
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Укажите адрес роутера без пути, пароля и параметров")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Некорректный порт роутера") from exc
        if timeout <= 0:
            raise ValueError("Тайм-аут должен быть положительным")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirects(),
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=context),
        )

    def _request(self, path: str, payload=None):
        if path not in {*READ_PATHS.values(), "/auth"}:
            raise ValueError("Путь отсутствует в списке диагностических методов")
        if payload is not None and path != "/auth":
            raise ValueError("Изменения конфигурации в этом прототипе выключены")
        return self._exchange(path, payload)

    def _exchange(self, path: str, payload=None):
        """Same-origin transport; callers must restrict paths and payloads."""
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status = response.code
                headers = response.headers
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise RouterError("network_error") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RouterError("response_too_large")
        return status, headers, raw

    def authenticate(self):
        status, headers, _ = self._request("/auth")
        if status == 200:
            return  # Existing session; the following RCI request still validates it.
        if status != 401:
            raise RouterError(f"auth_http_{status}")
        realm = headers.get("X-NDM-Realm")
        challenge = headers.get("X-NDM-Challenge")
        if not realm or not challenge:
            raise RouterError("unsupported_auth_scheme")
        digest = hashlib.md5(
            f"{self.username}:{realm}:{self.password()}".encode("utf-8")
        ).hexdigest()
        key = hashlib.sha256((challenge + digest).encode("utf-8")).hexdigest()
        status, _, raw = self._request(
            "/auth", {"login": self.username, "password": key}
        )
        if status != 200:
            raise RouterError(f"auth_http_{status}")
        if raw:
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise RouterError("auth_invalid_json") from None
            if has_rci_error(result):
                raise RouterError("auth_rci_error")

    def read(self, source: str):
        path = READ_PATHS[source]
        status, _, raw = self._request(path)
        if status == 401:
            self.authenticate()
            status, _, raw = self._request(path)
        if status != 200:
            raise RouterError(f"http_{status}")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RouterError("invalid_json") from None
        if has_rci_error(result):
            raise RouterError("rci_error")
        return result
