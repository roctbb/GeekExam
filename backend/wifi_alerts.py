"""Queue a confirmed classroom departure and relay it to Coding Projects."""
from datetime import timedelta
import hashlib
import hmac
import json
import time

import requests
from flask import current_app

import config as settings
from models import db
from presence_models import ExamWifiAlert, PresenceEvent
from time_utils import parse_utc, utc_iso

GRACE = timedelta(seconds=20)
ALERT_PATH = '/api/geekexam/wifi-disconnect'
FINAL_STATES = {'sent', 'no_recipient', 'uncertain', 'rejected'}


def queue_departure(config, attempt, binding, item, routers, complete):
    if not config.require_guard or not config.enabled or attempt.finished_at or not complete:
        return
    if item.get('state') != 'offline' or item.get('reason') != 'device_disconnected':
        return
    if (item.get('user_id') != attempt.user_id or item.get('device_id') != binding.guard_device_id
            or item.get('router_id') != binding.guard_router_id or attempt.user.role in ('teacher', 'admin')):
        return
    router = next((r for r in routers if r['id'] == binding.guard_router_id and r.get('fresh') is True), None)
    lost = parse_utc(item.get('since'))
    observed = parse_utc(router.get('observed_at')) if router else None
    if not lost or not observed or observed - lost < GRACE:
        return
    # Use the observation clock. Re-polling a cached snapshot cannot satisfy the grace period.
    gaps = db.session.scalars(db.select(PresenceEvent).where(
        PresenceEvent.attempt_id == attempt.id, PresenceEvent.kind == 'device_disconnected',
        PresenceEvent.router_id == binding.guard_router_id, PresenceEvent.started_at == lost,
        PresenceEvent.ended_at.is_(None)))
    for gap in gaps:
        if (gap.details.get('mass_disconnect') or gap.details.get('session_id') != binding.guard_session_id
                or db.session.get(ExamWifiAlert, gap.id)):
            continue
        db.session.add(ExamWifiAlert(event_id=gap.id, available_at=observed, payload={
            'event_id': gap.id, 'teacher_id': attempt.test.activated_by or attempt.test.created_by, 'student_name': attempt.user.name,
            'room_name': config.guard_room_name or config.guard_room_id, 'test_title': attempt.test.title,
            'disconnected_at': utc_iso(lost),
        }))


def send(payload):
    secret = settings.GEEKEXAM_ALERT_SECRET
    if len(secret) < 32:
        return 'retry', 60
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    prefix = f'POST\n{ALERT_PATH}\n{stamp}\n'.encode()
    signature = hmac.new(secret.encode(), prefix + body, hashlib.sha256).hexdigest()
    response = requests.post(settings.GEEKCLASS_HOST.rstrip('/') + ALERT_PATH, data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                 'X-Exam-Time': stamp, 'X-Exam-Signature': signature},
        timeout=(2, 12), allow_redirects=False)
    if response.status_code == 200:
        result = response.json()
        state = result.get('status') if isinstance(result, dict) else None
        if isinstance(state, str) and state in FINAL_STATES:
            return state, 0
    if response.status_code in (409, 422):
        return 'rejected', 0
    retry_after = response.headers.get('Retry-After', '')
    return 'retry', min(int(retry_after[:8]), 86400) if retry_after[:8].isdigit() else 0


def deliver_next(at):
    """Only lock the outbox row. CP deduplicates if the worker dies before commit."""
    alert = db.session.scalar(db.select(ExamWifiAlert).where(
        ExamWifiAlert.status == 'pending', ExamWifiAlert.available_at <= at
    ).order_by(ExamWifiAlert.available_at, ExamWifiAlert.event_id).limit(1).with_for_update(skip_locked=True))
    if not alert:
        db.session.rollback()
        return False
    alert.attempts += 1
    try:
        result, wait = send(alert.payload)
    except (requests.RequestException, ValueError):
        result, wait = 'retry', 0
    if result == 'retry':
        alert.available_at = at + timedelta(seconds=max(wait, min(5 * 2 ** min(alert.attempts, 9), 1800)))
    else:
        alert.status = result
    if result not in ('sent', 'retry') or (result == 'retry' and alert.attempts in (1, 5)):
        current_app.logger.warning('Wi-Fi alert %s delivery %s (attempt %d)', alert.event_id, result, alert.attempts)
    db.session.commit()
    return True
