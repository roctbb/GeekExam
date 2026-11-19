"""Connection evidence and per-test Guard admission settings."""
from datetime import datetime
import uuid
from models import db


def uid(): return str(uuid.uuid4())


class PresenceConfig(db.Model):
    __tablename__ = 'presence_configs'
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id',ondelete='CASCADE'), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    require_guard = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    guard_room_id = db.Column(db.String(36))
    guard_room_name = db.Column(db.String(120))
    configured_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    version = db.Column(db.Integer,nullable=False,default=1)
    __mapper_args__ = {'version_id_col':version}


class PresenceClient(db.Model):
    __tablename__ = 'presence_clients'
    id = db.Column(db.String(36),primary_key=True,default=uid)
    attempt_id = db.Column(db.Integer,db.ForeignKey('attempts.id',ondelete='CASCADE'),nullable=False,index=True)
    token_digest = db.Column(db.String(64),nullable=False)
    created_at = db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    last_sequence = db.Column(db.Integer,nullable=False,default=0)
    visible = db.Column(db.Boolean,nullable=False,default=True)


class PresenceHeartbeat(db.Model):
    __tablename__ = 'presence_heartbeats'
    id = db.Column(db.Integer,primary_key=True)
    attempt_id = db.Column(db.Integer,db.ForeignKey('attempts.id',ondelete='CASCADE'),nullable=False)
    client_id = db.Column(db.String(36),db.ForeignKey('presence_clients.id',ondelete='CASCADE'),nullable=False)
    sequence = db.Column(db.Integer,nullable=False)
    received_at = db.Column(db.DateTime,nullable=False)
    visible = db.Column(db.Boolean,nullable=False)
    __table_args__ = (db.UniqueConstraint('client_id','sequence',name='uq_presence_heartbeat_sequence'),
                     db.Index('ix_presence_heartbeat_attempt_time','attempt_id','received_at'))


class AttemptPresence(db.Model):
    __tablename__ = 'attempt_presence'
    attempt_id = db.Column(db.Integer,db.ForeignKey('attempts.id',ondelete='CASCADE'),primary_key=True)
    guard_session_id = db.Column(db.String(36))
    guard_device_id = db.Column(db.String(36))
    guard_router_id = db.Column(db.String(36))
    bound_client_id = db.Column(db.String(36))
    binding_confirmed_at = db.Column(db.DateTime)
    binding_observed_at = db.Column(db.DateTime)
    bound_by = db.Column(db.Integer,db.ForeignKey('users.id'))
    guard_state = db.Column(db.String(32),nullable=False,default='unbound')
    guard_reason = db.Column(db.String(80))
    guard_since = db.Column(db.DateTime)
    guard_last_confirmed_at = db.Column(db.DateTime)
    guard_checked_at = db.Column(db.DateTime)
    history_complete = db.Column(db.Boolean,nullable=False,default=True)


class PresenceEvent(db.Model):
    __tablename__ = 'presence_events'
    id = db.Column(db.String(36),primary_key=True,default=uid)
    test_id = db.Column(db.Integer,db.ForeignKey('tests.id',ondelete='CASCADE'),nullable=False,index=True)
    attempt_id = db.Column(db.Integer,db.ForeignKey('attempts.id',ondelete='CASCADE'),index=True)
    source_key = db.Column(db.String(64),nullable=False)
    kind = db.Column(db.String(40),nullable=False)
    router_id = db.Column(db.String(36))
    started_at = db.Column(db.DateTime,nullable=False)
    detected_at = db.Column(db.DateTime,nullable=False)
    last_confirmed_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    exam_continued_at = db.Column(db.DateTime)
    review_required = db.Column(db.Boolean,nullable=False,default=False)
    details = db.Column(db.JSON,nullable=False,default=dict)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer,db.ForeignKey('users.id'))
    review_note = db.Column(db.String(500))
    __table_args__ = (db.UniqueConstraint('test_id','source_key',name='uq_presence_event_source'),)
