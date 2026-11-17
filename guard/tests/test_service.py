from datetime import timedelta
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit
import uuid

import jwt

from conftest import observation
from guard_service.models import (db, Device, DeviceOverride, NetworkSession, Room, Router, StudentRule, User)
from guard_service.policy import parse_time, resolve_profile

CSRF = {"X-CSRF-Token": "test-csrf"}


def sync(app, headers, payload=None):
    response = app.test_client().post("/api/v1/agent/sync", json=payload or observation(), headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def device_id(app, router_id="router-a"):
    with app.app_context():
        return db.session.execute(db.select(Device.id).where(Device.router_id == router_id)).scalar_one()


def bind(app, login, headers):
    sync(app, headers)
    device = device_id(app)
    response = login(2).post(f"/api/v1/devices/{device}/binding", json={"user_id": 4, "epoch": "connection-1", "confirmed": True}, headers=CSRF)
    assert response.status_code == 201, response.json
    return device, response.json["session_id"]


def service_header(app, key, audience, sub):
    stamp = int(time.time())
    token = jwt.encode({"sub": sub, "aud": audience, "iat": stamp, "exp": stamp+30}, app.config[key], algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def test_teacher_sees_only_assigned_rooms_and_cannot_change_other_room(app, login):
    teacher = login(2)
    assert [item["id"] for item in teacher.get("/api/v1/rooms").json["items"]] == ["room-a"]
    assert teacher.get("/api/v1/rooms/room-b").status_code == 404
    assert teacher.patch("/api/v1/rooms/room-b", json={"version": 1, "manual_restriction": True}, headers=CSRF).status_code == 404
    assert len(login(1).get("/api/v1/rooms").json["items"]) == 2


def test_room_policy_updates_all_its_routers_only(app, login):
    response = login(2).patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": True}, headers=CSRF)
    assert response.status_code == 200
    assert response.json["restricted"] is True
    assert response.json["router_count"] == 2
    with app.app_context():
        assert db.session.get(Router, "router-a").desired_revision == 2
        assert db.session.get(Router, "router-a2").desired_revision == 2
        assert db.session.get(Router, "router-b").desired_revision == 1


def test_room_version_conflict_does_not_overwrite_newer_change(app, login):
    teacher = login(2)
    assert teacher.patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": True}, headers=CSRF).status_code == 200
    response = teacher.patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": False}, headers=CSRF)
    assert response.status_code == 409
    assert teacher.get("/api/v1/rooms/room-a").json["restricted"] is True


def test_csrf_student_role_and_admin_configuration_boundaries(app, login):
    assert login(2).patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": True}).status_code == 403
    assert login(4).patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": True}, headers=CSRF).status_code == 403
    assert login(2).patch("/api/v1/rooms/room-a", json={"version": 1, "resources": []}, headers=CSRF).status_code == 403
    assert login(2).post("/api/v1/routers", json={}, headers=CSRF).status_code == 403


def test_enrollment_is_single_use_and_old_machine_key_is_revoked(app, login, enroll):
    first, code = enroll("router-a")
    assert app.test_client().post("/api/v1/agent/enroll", json={"code": code}).status_code == 401
    second, _ = enroll("router-a")
    assert app.test_client().post("/api/v1/agent/sync", json=observation(), headers=first).status_code == 401
    assert sync(app, second)["policy"]["router_id"] == "router-a"


def test_same_mac_and_ip_are_isolated_between_routers(app, enroll):
    a, _ = enroll("router-a")
    b, _ = enroll("router-b")
    pa, pb = sync(app, a), sync(app, b)
    assert pa["policy"]["room_id"] == "room-a"
    assert pb["policy"]["room_id"] == "room-b"
    assert pa["policy"]["devices"][0]["id"] != pb["policy"]["devices"][0]["id"]


def test_agent_cannot_report_policy_issued_to_another_router(app, enroll):
    a, _ = enroll("router-a")
    b, _ = enroll("router-b")
    sync(app, a)
    other = sync(app, b)
    response = app.test_client().post("/api/v1/agent/report", headers=a, json={
        "id": str(uuid.uuid4()), "boot_id": "boot-one", "revision": other["policy"]["revision"],
        "policy_hash": other["policy_hash"], "mode": "enforce", "verified": True, "connections_revoked": False})
    assert response.status_code == 409


def test_observation_retries_are_idempotent_and_conflicting_sequence_is_rejected(app, enroll):
    headers, _ = enroll("router-a")
    payload = observation()
    first, second = sync(app, headers, payload), sync(app, headers, payload)
    assert first["policy_hash"] == second["policy_hash"]
    payload["devices"][0]["ip"] = "192.0.2.140"
    response = app.test_client().post("/api/v1/agent/sync", json=payload, headers=headers)
    assert response.status_code == 409


def test_new_boot_revokes_binding_and_old_boot_cannot_return(app, login, enroll):
    headers, _ = enroll("router-a")
    _, binding = bind(app, login, headers)
    sync(app, headers, observation(boot="boot-two"))
    with app.app_context():
        assert db.session.get(NetworkSession, binding).revoked_at is not None
    assert app.test_client().post("/api/v1/agent/sync", json=observation(sequence=1), headers=headers).status_code == 409


def test_incomplete_or_stale_source_does_not_mark_clients_offline_or_revoke_binding(app, login, enroll):
    headers, _ = enroll("router-a")
    device, binding = bind(app, login, headers)
    sync(app, headers, observation(sequence=1, devices=[], complete=False, source_error="associations_unavailable"))
    detail = login(2).get("/api/v1/rooms/room-a").json
    assert detail["devices"][0]["presence"] == "unknown"
    sync(app, headers, observation(sequence=2, devices=[], source_age_seconds=60))
    with app.app_context():
        assert db.session.get(Device, device).associated is True
        assert db.session.get(NetworkSession, binding).revoked_at is None


def test_complete_disconnection_revokes_session_and_presence_becomes_offline(app, login, enroll):
    headers, _ = enroll("router-a")
    _, binding = bind(app, login, headers)
    sync(app, headers, observation(sequence=1, devices=[]))
    assert login(2).get("/api/v1/rooms/room-a").json["devices"][0]["presence"] == "offline"
    with app.app_context():
        assert db.session.get(NetworkSession, binding).revoked_at is not None


def test_teacher_can_manage_student_but_device_exceptions_require_admin(app, login, enroll):
    headers, _ = enroll("router-a")
    device, binding = bind(app, login, headers)
    student_rule = {"profile": "platform_only", "seconds": 600, "reason": "Контрольная"}
    assert login(2).put(f"/api/v1/sessions/{binding}/access", json=student_rule, headers=CSRF).status_code == 200
    assert login(2).put(f"/api/v1/devices/{device}/override", json={"reason": "Камера"}, headers=CSRF).status_code == 403
    response = login(1).put(f"/api/v1/devices/{device}/override", json={"reason": "Камера"}, headers=CSRF)
    assert response.status_code == 200
    assert response.json["profile"] == "full"
    assert login(1).delete(f"/api/v1/devices/{device}/override", headers=CSRF).json["profile"] == "platform_only"
    assert login(1).put(f"/api/v1/sessions/{binding}/access", json=student_rule, headers=CSRF).status_code == 200


def test_teacher_cannot_bind_foreign_student_or_another_admin(app, login, enroll):
    headers, _ = enroll("router-a")
    sync(app, headers)
    device = device_id(app)
    for user_id in (1, 3, 5):
        response = login(2).post(f"/api/v1/devices/{device}/binding", json={"user_id": user_id, "epoch": "connection-1", "confirmed": True}, headers=CSRF)
        assert response.status_code == 403


def test_binding_requires_fresh_epoch_and_role_is_never_taken_from_browser(app, login, enroll):
    headers, _ = enroll("router-a")
    sync(app, headers)
    device = device_id(app)
    response = login(2).post(f"/api/v1/devices/{device}/binding", json={"user_id": 4, "epoch": "old", "confirmed": True}, headers=CSRF)
    assert response.status_code == 409
    response = login(2).post(f"/api/v1/devices/{device}/binding", json={"user_id": 4, "epoch": "connection-1", "confirmed": True, "role": "admin"}, headers=CSRF)
    assert response.status_code == 400


def test_temporal_choices_expire_locally_without_new_server_revision(app, login, enroll):
    headers, _ = enroll("router-a")
    device, binding = bind(app, login, headers)
    login(2).patch("/api/v1/rooms/room-a", json={"version": 1, "manual_restriction": True}, headers=CSRF)
    login(2).put(f"/api/v1/sessions/{binding}/access", json={"profile": "full", "seconds": 60, "reason": "Документация"}, headers=CSRF)
    policy = sync(app, headers, observation(sequence=1))["policy"]
    choices = policy["devices"][0]["choices"]
    assert resolve_profile(choices, True, app.clock())[0] == "full"
    assert resolve_profile(choices, True, app.clock()+timedelta(seconds=61))[0] == "platform_only"


def test_moving_router_to_another_room_revokes_bindings_and_old_teacher_loses_access(app, login, enroll):
    headers, _ = enroll("router-a")
    device, binding = bind(app, login, headers)
    response = login(1).patch("/api/v1/routers/router-a", json={"version": 1, "room_id": "room-b"}, headers=CSRF)
    assert response.status_code == 200
    assert login(2).post(f"/api/v1/devices/{device}/binding", json={"user_id": 4, "epoch": "connection-1", "confirmed": True}, headers=CSRF).status_code == 404
    with app.app_context():
        assert db.session.get(NetworkSession, binding).revoked_at is not None


def test_two_exam_restrictions_and_manual_switch_are_independent(app, login):
    header = service_header(app, "EXAM_SERVICE_SECRET", "guard:exams", "geekexam")
    client = app.test_client()
    for test in ("test-one", "test-two"):
        assert client.put(f"/api/v1/internal/exams/rooms/room-a/restrictions/{test}", json={"actor_id": 2, "reason": test}, headers=header).status_code == 200
    response = client.delete("/api/v1/internal/exams/rooms/room-a/restrictions/test-one", json={"actor_id": 2}, headers=header)
    assert response.json["restricted"] is True
    version = response.json["version"]
    login(2).patch("/api/v1/rooms/room-a", json={"version": version, "manual_restriction": True}, headers=CSRF)
    response = client.delete("/api/v1/internal/exams/rooms/room-a/restrictions/test-two", json={"actor_id": 2}, headers=header)
    assert response.json["restricted"] is True
    assert response.json["restrictions"] == []


def test_observe_mode_cannot_claim_successful_enforcement(app, login, enroll):
    header, _ = enroll("router-a")
    result = sync(app, header)
    payload = {"id": str(uuid.uuid4()), "boot_id": "boot-one", "revision": result["policy"]["revision"],
               "policy_hash": result["policy_hash"], "mode": "observe", "verified": True, "connections_revoked": False}
    assert app.test_client().post("/api/v1/agent/report", json=payload, headers=header).status_code == 400
    routers = login(2).get("/api/v1/rooms/room-a").json["routers"]
    assert next(item for item in routers if item["id"] == "router-a")["status"] == "observe"


def test_partial_room_status_requires_each_router_ack(app, login, enroll):
    h1, _ = enroll("router-a")
    h2, _ = enroll("router-a2")
    result = sync(app, h1, observation(mode="enforce"))
    sync(app, h2, observation(mode="enforce"))
    payload = {"id": str(uuid.uuid4()), "boot_id": "boot-one", "revision": result["policy"]["revision"],
               "policy_hash": result["policy_hash"], "mode": "enforce", "verified": True, "connections_revoked": False}
    assert app.test_client().post("/api/v1/agent/report", json=payload, headers=h1).status_code == 200
    room = login(2).get("/api/v1/rooms/room-a").json
    assert room["status"] == "partial" and room["applied_count"] == 1


def test_presence_expires_to_unknown_without_false_disconnect(app, login, enroll):
    headers, _ = enroll("router-a")
    bind(app, login, headers)
    app.clock.value += timedelta(seconds=21)
    assert login(2).get("/api/v1/rooms/room-a").json["devices"][0]["presence"] == "unknown"


def test_identity_sync_is_signed_and_revoked_role_takes_effect(app, login):
    client = login(1)
    assert client.post("/api/v1/internal/identities", json={"users": []}, headers=CSRF).status_code == 401
    header = service_header(app, "CP_SERVICE_SECRET", "guard:identities", "codingprojects")
    response = app.test_client().post("/api/v1/internal/identities", json={"users": [{"id": 1, "name": "Бывший админ", "role": "student"}]}, headers=header)
    assert response.status_code == 200
    assert client.post("/api/v1/rooms", json={"name": "999"}, headers=CSRF).status_code == 403


def test_sso_requires_state_and_rejects_token_replay(app):
    client = app.test_client()
    redirect = client.get("/auth/login")
    callback = parse_qs(urlsplit(redirect.location).query)["redirect_url"][0]
    token = jwt.encode({"id": 20, "name": "Новый преподаватель", "role": "teacher", "iat": int(time.time()),
                        "iss": "codingprojects", "purpose": "service-login", "service_origin": app.config["PUBLIC_URL"]}, app.config["CP_JWT_SECRET"], algorithm="HS256")
    response = client.get(callback.replace(app.config["PUBLIC_URL"], "") + "&token=" + token)
    assert response.status_code == 302
    assert client.get("/api/me").json["role"] == "teacher"
    second = app.test_client()
    callback2 = parse_qs(urlsplit(second.get("/auth/login").location).query)["redirect_url"][0]
    assert second.get(callback2.replace(app.config["PUBLIC_URL"], "") + "&token=" + token).status_code == 403
    assert app.test_client().get("/auth/callback?state=wrong&token=" + token).status_code == 403


def test_sso_rejects_old_future_and_wrongly_signed_tokens(app):
    for offset, secret in ((-120, app.config["CP_JWT_SECRET"]), (120, app.config["CP_JWT_SECRET"]), (0, "wrong-secret-" * 4)):
        client = app.test_client()
        callback = parse_qs(urlsplit(client.get("/auth/login").location).query)["redirect_url"][0]
        token = jwt.encode({"id": 20, "name": "Учитель", "role": "teacher", "iat": int(time.time())+offset,
                            "iss": "codingprojects", "purpose": "service-login", "service_origin": app.config["PUBLIC_URL"]}, secret, algorithm="HS256")
        assert client.get(callback.replace(app.config["PUBLIC_URL"], "") + "&token=" + token).status_code == 403


def test_sso_rejects_tokens_issued_to_another_service_or_purpose(app):
    for changed in ({"service_origin":"https://exam.geekclass.ru"}, {"purpose":"other"}, {"iss":"other"}):
        client = app.test_client()
        callback = parse_qs(urlsplit(client.get("/auth/login").location).query)["redirect_url"][0]
        claims = {"id":20,"name":"Учитель","role":"teacher","iat":int(time.time()),
                  "iss":"codingprojects","purpose":"service-login","service_origin":app.config["PUBLIC_URL"], **changed}
        token = jwt.encode(claims, app.config["CP_JWT_SECRET"], algorithm="HS256")
        assert client.get(callback.replace(app.config["PUBLIC_URL"], "") + "&token=" + token).status_code == 403


def test_codingprojects_novice_has_student_permissions_only(app):
    client = app.test_client()
    callback = parse_qs(urlsplit(client.get("/auth/login").location).query)["redirect_url"][0]
    claims = {"id":20,"name":"Новичок","role":"novice","iat":int(time.time()),
              "iss":"codingprojects","purpose":"service-login","service_origin":app.config["PUBLIC_URL"]}
    token = jwt.encode(claims, app.config["CP_JWT_SECRET"], algorithm="HS256")
    assert client.get(callback.replace(app.config["PUBLIC_URL"], "") + "&token=" + token).status_code == 302
    assert client.get("/api/me").json["role"] == "student"
    assert client.get("/api/v1/rooms").status_code == 403


def test_operator_bootstrap_writes_one_time_credentials_without_enabling_filtering(app, tmp_path):
    path = tmp_path / "router.json"
    result = app.test_cli_runner().invoke(args=["bootstrap-router","--room","409","--name","New router","--output",str(path)])
    assert result.exit_code == 0, result.output
    data = json.loads(path.read_text())
    assert path.stat().st_mode & 0o777 == 0o600
    with app.app_context():
        router = db.session.get(Router, data["router_id"])
        assert router.room_id == "room-a" and router.mode == "observe"
    client = app.test_client()
    assert client.post("/api/v1/agent/enroll", json={"code":data["code"]}).status_code == 201
    second = tmp_path / "second.json"
    result = app.test_cli_runner().invoke(args=["bootstrap-router","--room","409","--name","New router","--output",str(second)])
    assert result.exit_code != 0 and not second.exists()
    assert client.post("/api/v1/agent/enroll", json={"code":data["code"]}).status_code == 401


def test_student_cannot_read_devices_after_binding_expires(app, login, enroll):
    header, _ = enroll("router-a")
    device, binding = bind(app, login, header)
    student = login(4)
    assert student.get("/api/v1/my-network").json["items"][0]["id"] == device
    app.clock.value += timedelta(hours=9)
    assert student.get("/api/v1/my-network").json["items"] == []


def test_exam_presence_is_specific_scoped_and_expired_binding_is_unknown(app, login, enroll):
    header, _ = enroll("router-a")
    _device, binding = bind(app, login, header)
    auth = service_header(app, "EXAM_SERVICE_SECRET", "guard:exams", "geekexam")
    client = app.test_client()
    path = "/api/v1/internal/presence/query"
    assert client.post(path, json={"actor_id":2,"session_ids":[binding]}).status_code == 401
    response = client.post(path, json={"actor_id":2,"session_ids":[binding]}, headers=auth)
    assert response.json["items"][0]["presence"] == "online"
    assert client.post(path, json={"actor_id":3,"session_ids":[binding]}, headers=auth).status_code == 404
    app.clock.value += timedelta(hours=9)
    sync(app, header, observation(1))  # Fresh physical association, expired identity binding.
    response = client.post(path, json={"actor_id":2,"session_ids":[binding]}, headers=auth)
    assert response.json["items"][0]["presence"] == "unknown"
    assert response.json["items"][0]["bound"] is False
