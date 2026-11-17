#!/usr/bin/env python3
"""Loopback-only demo. No connection to a real router or Coding Projects."""
from datetime import timedelta, timezone
import html
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jwt
from flask import Flask, redirect, request
from werkzeug.serving import make_server, WSGIRequestHandler

from guard_service import create_app
from guard_service.models import (db, Device, DeviceOverride, NetworkSession, Room, Router,
                                  Segment, StudentRoom, TeacherRoom, User, utcnow)
from guard_service.security import digest


class Quiet(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass  # In particular, do not log JWT-bearing callback query strings.


def main():
    directory = Path(tempfile.mkdtemp(prefix="guard-demo-"))
    cp_secret = secrets.token_urlsafe(48)
    app = create_app({"SECRET_KEY": secrets.token_urlsafe(48), "DEMO": True,
                      "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(directory / "demo.sqlite"),
                      "PUBLIC_URL": "http://127.0.0.1:8088", "CP_URL": "http://127.0.0.1:8089",
                      "CP_JWT_SECRET": cp_secret})
    identities = [(1, "Ростислав", "admin"), (2, "Анна · преподаватель", "teacher"),
                  (3, "Михаил Соколов", "student"), (4, "Алиса Волкова", "student"),
                  (5, "Даниил Морозов", "student"), (6, "Софья Орлова", "student")]
    tokens, devices = {}, {}
    with app.app_context():
        db.create_all()
        db.session.add_all([User(id=i, name=name, role=role, role_expires_at=utcnow()+timedelta(days=1)) for i, name, role in identities])
        db.session.add_all([Room(id="demo-room-409", name="409", description="Информатика · учебная сеть 409",
                                manual_restriction=True, resources=[{"ip": "195.133.49.12", "port": 443}]),
                            Room(id="demo-room-410", name="410", description="Проектная лаборатория",
                                 resources=[{"ip": "195.133.49.12", "port": 443}])])
        db.session.flush()
        db.session.add(TeacherRoom(room_id="demo-room-409", user_id=2))
        for user_id in (3, 4, 5):
            db.session.add(StudentRoom(room_id="demo-room-409", user_id=user_id))
        db.session.add(StudentRoom(room_id="demo-room-410", user_id=6))
        for key, name, room in [("409-main", "Основной · Challenger", "409"), ("409-second", "Дополнительный · Hopper", "409"), ("410-main", "Лаборатория · Hopper", "410")]:
            token = secrets.token_urlsafe(48)
            tokens[key] = token
            db.session.add(Router(id=key, room_id="demo-room-"+room, name=name, token_digest=digest(token)))
        db.session.flush()
        for key in tokens:
            db.session.add(Segment(id="segment-"+key, router_id=key, name="Учебный Wi-Fi", interface="Bridge1", purpose="student"))
        db.session.commit()
        devices = {
            "409-main": [{"mac":"02:00:00:00:01:01","ip":"192.168.12.21","name":"MacBook Air · Михаил","epoch":"demo-mikhail","interface":"Bridge1"},
                         {"mac":"02:00:00:00:01:02","ip":"192.168.12.34","name":"Ноутбук · Алиса","epoch":"demo-alisa","interface":"Bridge1"},
                         {"mac":"02:00:00:00:01:03","ip":"192.168.12.10","name":"Ноутбук преподавателя","epoch":"demo-teacher","interface":"Bridge1"},
                         {"mac":"02:00:00:00:01:04","ip":"192.168.12.8","name":"Принтер · 409","epoch":"demo-printer","interface":"Bridge1"}],
            "409-second": [{"mac":"02:00:00:00:02:01","ip":"192.168.13.26","name":"Ноутбук · Даниил","epoch":"demo-daniil","interface":"Bridge1"},
                           {"mac":"02:00:00:00:02:02","ip":"192.168.13.39","name":"Неизвестный телефон","epoch":"demo-unknown","interface":"Bridge1"}],
            "410-main": [{"mac":"02:00:00:00:03:01","ip":"192.168.12.21","name":"Ноутбук · Софья","epoch":"demo-sofia","interface":"Bridge1"}]}

    def sync(key, sequence):
        with app.test_client() as client:
            return client.post("/api/v1/agent/sync", headers={"Authorization": "Bearer "+tokens[key]},
                               json={"boot_id":"demo-boot-"+key, "sequence":sequence, "complete":True, "devices":devices[key],
                                     "mode":"observe", "model":"Keenetic / Netcraze · демо", "firmware":"5.1",
                                     "capabilities":{"ipv4_filter":True,"ipv6_filter":False,"connections_revocation":False}})

    for key in tokens:
        assert sync(key, 0).status_code == 200
    with app.app_context():
        mapping = {"demo-mikhail":3,"demo-alisa":4,"demo-teacher":2,"demo-daniil":5,"demo-sofia":6}
        for device in db.session.execute(db.select(Device)).scalars():
            if device.epoch in mapping:
                db.session.add(NetworkSession(device_id=device.id, user_id=mapping[device.epoch], boot_id="demo-boot-"+device.router_id,
                                               epoch=device.epoch, expires_at=utcnow()+timedelta(hours=3), created_by=1))
            if device.epoch == "demo-printer":
                db.session.add(DeviceOverride(device_id=device.id, reason="Принтер кабинета", created_by=1))
        for router in db.session.execute(db.select(Router)).scalars():
            router.desired_revision += 1
        db.session.commit()

    fake_cp = Flask("guard_demo_identity_provider")

    @fake_cp.get("/insider/jwt")
    def choose_identity():
        callback = request.args.get("redirect_url", "")
        parsed = urlsplit(callback)
        if parsed.scheme != "http" or parsed.netloc != "127.0.0.1:8088" or parsed.path != "/auth/callback":
            return "Invalid local callback", 400
        chosen = request.args.get("demo_user", type=int)
        if chosen is None:
            links = "".join('<a href="?'+html.escape(urlencode({"redirect_url":callback,"demo_user":i}), quote=True)+'">'+html.escape(name)+" · "+role+"</a>" for i,name,role in identities if i in (1,2,3))
            return '<meta name="viewport" content="width=device-width"><title>Демо · вход Guard</title><style>body{font:16px system-ui;background:#f5f6f2;color:#23372d;max-width:560px;margin:90px auto;padding:25px}a{display:block;padding:18px;margin:15px 0;background:white;border:1px solid #dce5d4;border-radius:8px;color:#426e44;text-decoration:none}p{line-height:1.7;color:#7e8f74}</style><h1>Демонстрационный вход</h1><p>Локальная имитация Coding Projects. Выберите роль для проверки интерфейса.</p>'+links
        person = next((person for person in identities if person[0] == chosen), None)
        if not person:
            return "Unknown demo user", 400
        i, name, role = person
        token = jwt.encode({"id":i,"name":name,"role":role,"iat":int(time.time()),"jti":str(uuid.uuid4()),
                            "iss":"codingprojects","purpose":"service-login","service_origin":"http://127.0.0.1:8088"}, cp_secret, algorithm="HS256")
        return redirect(callback+"&"+urlencode({"token":token}))

    server = make_server("127.0.0.1", 8088, app, threaded=True, request_handler=Quiet)
    identity_server = make_server("127.0.0.1", 8089, fake_cp, threaded=True, request_handler=Quiet)
    threading.Thread(target=identity_server.serve_forever, daemon=True).start()

    def agent_loop():
        sequence = 1
        while True:
            for key in tokens:
                response = sync(key, sequence)
                if response.status_code != 200:
                    print("Demo agent sync error", response.status_code, flush=True)
            sequence += 1
            time.sleep(5)

    threading.Thread(target=agent_loop, daemon=True).start()
    print("Guard demo: http://127.0.0.1:8088 · только локальная демонстрация", flush=True)
    print("База демо: "+str(directory / "demo.sqlite"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        identity_server.shutdown()


if __name__ == "__main__":
    main()
