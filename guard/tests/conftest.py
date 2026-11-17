from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from guard_service import create_app
from guard_service.models import db, Room, Router, Segment, StudentRoom, TeacherRoom, User


class Clock:
    def __init__(self):
        self.value = datetime.now(timezone.utc).replace(tzinfo=None)

    def __call__(self):
        return self.value


@pytest.fixture
def app():
    clock = Clock()
    app = create_app({"TESTING": True, "SECRET_KEY": "test-session-" * 4,
                      "SQLALCHEMY_DATABASE_URI": "sqlite://", "PUBLIC_URL": "http://127.0.0.1:8088",
                      "CP_JWT_SECRET": "test-cp-" * 6, "CP_SERVICE_SECRET": "test-identity-" * 4,
                      "EXAM_SERVICE_SECRET": "test-exam-" * 5, "NOW": clock})
    app.clock = clock
    with app.app_context():
        db.create_all()
        db.session.add_all([User(id=i, name=name, role=role, role_expires_at=clock()+timedelta(days=1))
                            for i, name, role in [(1, "Администратор", "admin"), (2, "Учитель 409", "teacher"),
                                                   (3, "Учитель 410", "teacher"), (4, "Ученик 409", "student"), (5, "Ученик 410", "student")]])
        db.session.add_all([Room(id="room-a", name="409", resources=[{"ip": "93.184.215.14", "port": 443}]),
                            Room(id="room-b", name="410", resources=[{"ip": "93.184.215.14", "port": 443}])])
        db.session.flush()
        db.session.add_all([TeacherRoom(room_id="room-a", user_id=2), TeacherRoom(room_id="room-b", user_id=3),
                            StudentRoom(room_id="room-a", user_id=4), StudentRoom(room_id="room-b", user_id=5)])
        db.session.add_all([Router(id="router-a", room_id="room-a", name="Основной"),
                            Router(id="router-a2", room_id="room-a", name="Второй"),
                            Router(id="router-b", room_id="room-b", name="410")])
        db.session.flush()
        db.session.add_all([Segment(id=f"segment-{key}", router_id=f"router-{key}", name="Ученики", interface="Bridge0", purpose="student")
                            for key in ("a", "a2", "b")])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def login(app):
    def make_client(user_id):
        client = app.test_client()
        with client.session_transaction() as state:
            state.update(user_id=user_id, csrf="test-csrf")
        return client
    return make_client


@pytest.fixture
def enroll(app, login):
    def perform(router_id):
        response = login(1).post(f"/api/v1/routers/{router_id}/enrollment", headers={"X-CSRF-Token": "test-csrf"})
        assert response.status_code == 200
        code = response.json["code"]
        response = app.test_client().post("/api/v1/agent/enroll", json={"code": code})
        assert response.status_code == 201
        return {"Authorization": "Bearer " + response.json["token"]}, code
    return perform


def observation(sequence=0, boot="boot-one", devices=None, **kwargs):
    return {"boot_id": boot, "sequence": sequence, "complete": True, "mode": "observe",
            "devices": devices if devices is not None else [
                {"mac": "02:00:00:00:00:01", "ip": "192.0.2.139", "name": "Телефон", "epoch": "connection-1", "interface": "Bridge0"}], **kwargs}
