"""Run with Python 3.10+, without installing the Guard server dependencies."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import getpass
import ipaddress
import json
from pathlib import Path
import re
import signal
import sys
import time
from urllib.parse import urlsplit
import uuid

from .enforcer import Enforcer
from .observer import Observer
from .policy import fingerprint, parse_time, validate_policy
from .rci import RciClient, RouterError
from .transport import GuardClient, private_read, private_write


def config_read(path, *, enrolled=True):
    config = private_read(path)
    interfaces = config.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces or len(set(interfaces)) != len(interfaces) or any(not isinstance(i, str) or not re.fullmatch(r"Bridge[0-9]{1,2}", i) for i in interfaces):
        raise RouterError("invalid_local_interfaces")
    student = config.get("student_interfaces", [])
    if not isinstance(student, list) or set(student) - set(interfaces):
        raise RouterError("invalid_local_student_interfaces")
    try:
        address = ipaddress.ip_address(urlsplit(config["router_url"]).hostname)
        if not address.is_private or address.is_loopback or address.version != 4:
            raise ValueError()
    except (KeyError, ValueError):
        raise RouterError("router_requires_private_lan_ipv4") from None
    if enrolled and (not config.get("router_id") or not config.get("token")):
        raise RouterError("enrollment_required")
    return config


def password_source(config):
    filename = config.get("password_file")
    if filename:
        path = Path(filename).expanduser()
        if path.stat().st_mode & 0o077:
            raise RouterError("password_file_must_have_mode_0600")
        value = path.read_text().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise RouterError("password_file_or_interactive_terminal_required")
        value = getpass.getpass("Пароль роутера (остаётся на этом устройстве): ")
    if not value:
        raise RouterError("empty_router_password")
    return lambda: value


def run(config, config_path, *, enforce=False, once=False):
    if enforce and (not config.get("experimental_ipv4_enforcement") or not config.get("student_interfaces")):
        raise RouterError("experimental_dedicated_student_segment_opt_in_required")
    cloud = GuardClient(config["guard_url"], config["token"])
    password = password_source(config)
    rci = RciClient(config["router_url"], config.get("username", "admin"), password, timeout=4)
    observer = Observer(rci, config["interfaces"])
    driver = Enforcer(config["router_url"], config.get("username", "admin"), password, timeout=4,
                      router_id=config["router_id"], interfaces=config["student_interfaces"]) if enforce else None
    mode, boot, sequence = "enforce" if enforce else "observe", str(uuid.uuid4()), 0
    cache_path = Path(str(config_path) + ".policy.json")
    policy, anchored_at, server_time, last_report, last_message = None, None, None, None, None
    if driver and cache_path.exists():
        cached = private_read(cache_path)
        policy = validate_policy(cached["policy"], config["router_id"], config["interfaces"])
        # A restart cannot resurrect any cached positive grant, including exceptions.
        for device in policy["devices"]:
            device["choices"] = [{"profile": "bootstrap", "when": "always", "expires_at": None, "requires_session": False}]
        driver.apply(policy, [], datetime.now(timezone.utc), session_grants=False)
        policy = None
    stopping = False

    def stop(_number, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Guard agent: " + mode + "; пароли роутера на сервер не отправляются.", flush=True)
    try:
        while not stopping:
            start = time.monotonic()
            observations, source_error = [], None
            try:
                observations = observer.read()
            except (RouterError, OSError, ValueError, KeyError, TypeError) as exc:
                source_error = str(exc) if isinstance(exc, RouterError) else "router_observation_failed"
            message = {"boot_id": boot, "sequence": sequence, "complete": source_error is None,
                       "devices": observations, "mode": mode, "source_age_seconds": int(time.monotonic()-start),
                       "capabilities": {"ipv4_filter": bool(driver), "ipv6_filter": False, "connections_revocation": False}}
            if source_error:
                message["source_error"] = source_error
            # A fresh sequence/sample after a timeout avoids re-dating old evidence.
            sequence += 1
            cloud_error, confirmed = None, False
            try:
                response = cloud.post("sync", message)
                document = validate_policy(response["policy"], config["router_id"], config["interfaces"])
                if fingerprint(document) != response["policy_hash"]:
                    raise RouterError("policy_hash_mismatch")
                remote_students = {s["interface"] for s in document["segments"] if s["purpose"] == "student"}
                if driver and remote_students != set(config["student_interfaces"]):
                    raise RouterError("student_interfaces_require_local_confirmation")
                policy, server_time, anchored_at = document, parse_time(response["server_time"]), time.monotonic()
                private_write(cache_path, response)
                confirmed = True
            except (RouterError, OSError, ValueError, KeyError, TypeError) as exc:
                cloud_error = str(exc) if isinstance(exc, RouterError) else "guard_sync_failed"
            apply_error, verified = None, False
            if policy and driver:
                local_now = server_time + timedelta(seconds=time.monotonic()-anchored_at)
                fresh = source_error is None and time.monotonic()-anchored_at <= 20
                try:
                    driver.apply(policy, observations, local_now, session_grants=fresh)
                    verified = confirmed and source_error is None
                except (RouterError, OSError, ValueError, KeyError, TypeError) as exc:
                    apply_error = str(exc) if isinstance(exc, RouterError) else "router_apply_failed"
            if policy and confirmed:
                report = {"boot_id": boot, "revision": policy["revision"], "policy_hash": fingerprint(policy),
                          "mode": mode, "verified": verified, "connections_revoked": False,
                          "error": apply_error or source_error or ""}
                signature = fingerprint(report)
                if last_report != signature:
                    try:
                        cloud.post("report", {**report, "id": str(uuid.uuid4())})
                        last_report = signature
                    except RouterError as exc:
                        cloud_error = str(exc)
            status = apply_error or source_error or cloud_error or ("ipv4_acl_verified" if verified else "observing")
            if status != last_message:
                print(json.dumps({"status": status, "revision": policy["revision"] if policy else None}, ensure_ascii=False), flush=True)
                last_message = status
            if once:
                return 1 if apply_error or source_error or cloud_error else 0
            while not stopping and time.monotonic()-start < 5:
                time.sleep(.2)
    finally:
        if driver:
            print("Агент остановлен; установленные ACL оставлены. release снимает только ACL Guard.", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Guard: локальный агент KeeneticOS / Netcraze")
    parser.add_argument("action", choices=["enroll", "run", "release"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--enforce-experimental-ipv4", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        config = config_read(args.config, enrolled=args.action != "enroll")
        # One process per credential/configuration file.
        lock_path = Path(str(args.config) + ".lock").expanduser()
        descriptor = lock_path.open("a")
        lock_path.chmod(0o600)
        with descriptor:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RouterError("another_agent_uses_this_config") from None
            if args.action == "enroll":
                code = getpass.getpass("Одноразовый код из Guard: ")
                result = GuardClient(config["guard_url"]).post("enroll", {"code": code})
                config.update(router_id=result["router_id"], token=result["token"])
                private_write(args.config, config)
                print("Агент зарегистрирован. Машинный ключ сохранён в файле 0600.")
                return 0
            if args.action == "release":
                driver = Enforcer(config["router_url"], config.get("username", "admin"), password_source(config),
                                  router_id=config["router_id"], interfaces=config["student_interfaces"])
                driver.release()
                print("Собственные ACL Guard сняты; результат проверен чтением роутера.")
                return 0
            return run(config, args.config, enforce=args.enforce_experimental_ipv4, once=args.once)
    except (RouterError, OSError, ValueError, KeyError, TypeError) as exc:
        print("Ошибка: " + (str(exc) if isinstance(exc, RouterError) else type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
