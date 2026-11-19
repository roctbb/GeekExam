from datetime import datetime, timezone
import uuid

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy(session_options={"expire_on_commit": False})


def uid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # Coding Projects ID
    name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(16), nullable=False)
    role_expires_at = db.Column(db.DateTime, nullable=False)


class LoginTicket(db.Model):
    digest = db.Column(db.String(64), primary_key=True)
    expires_at = db.Column(db.DateTime, nullable=False)


class Room(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(500), nullable=False, default="")
    manual_restriction = db.Column(db.Boolean, nullable=False, default=False)
    resources = db.Column(db.JSON, nullable=False, default=list)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}


class TeacherRoom(db.Model):
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)


class StudentRoom(db.Model):
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)


class Router(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    config_version = db.Column(db.Integer, nullable=False, default=1)
    desired_revision = db.Column(db.Integer, nullable=False, default=1)
    token_digest = db.Column(db.String(64), unique=True)
    enroll_digest = db.Column(db.String(64), unique=True)
    enroll_expires_at = db.Column(db.DateTime)
    boot_id = db.Column(db.String(80))
    last_sequence = db.Column(db.Integer, nullable=False, default=-1)
    last_observation_digest = db.Column(db.String(64))
    last_seen = db.Column(db.DateTime)
    observation_at = db.Column(db.DateTime)
    source_error = db.Column(db.String(160))
    model = db.Column(db.String(120), nullable=False, default="")
    firmware = db.Column(db.String(80), nullable=False, default="")
    capabilities = db.Column(db.JSON, nullable=False, default=dict)
    applied_revision = db.Column(db.Integer)
    applied_at = db.Column(db.DateTime)
    apply_error = db.Column(db.String(300))
    mode = db.Column(db.String(20), nullable=False, default="observe")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}


class AgentBoot(db.Model):
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), primary_key=True)
    boot_id = db.Column(db.String(80), primary_key=True)
    retired = db.Column(db.Boolean, nullable=False, default=False)


class Segment(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    interface = db.Column(db.String(40), nullable=False)
    purpose = db.Column(db.String(20), nullable=False, default="student")
    __table_args__ = (db.UniqueConstraint("router_id", "interface"),)


class Device(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), nullable=False, index=True)
    segment_id = db.Column(db.String(36), db.ForeignKey("segment.id"), nullable=False, index=True)
    mac = db.Column(db.String(17), nullable=False)
    ip = db.Column(db.String(45))
    name = db.Column(db.String(160), nullable=False, default="")
    epoch = db.Column(db.String(100), nullable=False)
    associated = db.Column(db.Boolean, nullable=False, default=True)
    observed_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("router_id", "mac"),)


class NetworkSession(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    device_id = db.Column(db.String(36), db.ForeignKey("device.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    boot_id = db.Column(db.String(80), nullable=False)
    epoch = db.Column(db.String(100), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    method = db.Column(db.String(30), nullable=False, default="teacher_confirmed")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class StudentRule(db.Model):
    session_id = db.Column(db.String(36), db.ForeignKey("network_session.id"), primary_key=True)
    profile = db.Column(db.String(20), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class LocalProofEndpoint(db.Model):
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), primary_key=True)
    origin = db.Column(db.String(250), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}


class BrowserProof(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    token_digest = db.Column(db.String(64), nullable=False, unique=True)
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), nullable=False)
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    attempt_id = db.Column(db.Integer, nullable=False, index=True)
    client_id = db.Column(db.String(36), nullable=False)
    browser_origin = db.Column(db.String(250), nullable=False)
    endpoint_origin = db.Column(db.String(250), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    consumed_at = db.Column(db.DateTime)
    device_id = db.Column(db.String(36), db.ForeignKey("device.id"))
    session_id = db.Column(db.String(36), db.ForeignKey("network_session.id"))
    boot_id = db.Column(db.String(80))
    epoch = db.Column(db.String(100))


class DeviceOverride(db.Model):
    device_id = db.Column(db.String(36), db.ForeignKey("device.id"), primary_key=True)
    expires_at = db.Column(db.DateTime)
    reason = db.Column(db.String(300), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class NetworkLogin(db.Model):
    """One-use LAN challenge owned by an authenticated Coding Projects user."""
    id = db.Column(db.String(36), primary_key=True, default=uid)
    token_digest = db.Column(db.String(64), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), nullable=False)
    endpoint_origin = db.Column(db.String(250), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    session_id = db.Column(db.String(36), db.ForeignKey("network_session.id"))


class Restriction(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), nullable=False, index=True)
    source = db.Column(db.String(40), nullable=False)
    external_id = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    expires_at = db.Column(db.DateTime)
    released_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint("room_id", "source", "external_id"),)


class PolicySnapshot(db.Model):
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), primary_key=True)
    revision = db.Column(db.Integer, primary_key=True)
    digest = db.Column(db.String(64), nullable=False)
    document = db.Column(db.JSON, nullable=False)


class ApplyReport(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    router_id = db.Column(db.String(36), db.ForeignKey("router.id"), nullable=False, index=True)
    revision = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    mode = db.Column(db.String(20), nullable=False)
    verified = db.Column(db.Boolean, nullable=False)
    connections_revoked = db.Column(db.Boolean, nullable=False, default=False)
    error = db.Column(db.String(300))


class AuditEvent(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    room_id = db.Column(db.String(36), db.ForeignKey("room.id"), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    event = db.Column(db.String(60), nullable=False)
    target_id = db.Column(db.String(120), nullable=False)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
