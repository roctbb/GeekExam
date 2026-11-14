"""Platform-owned immutable submissions, snapshots, results and file references."""
from datetime import datetime
from models import db


class ExecutionRun(db.Model):
    __tablename__ = 'execution_runs'
    id = db.Column(db.String(36), primary_key=True)
    submission_id = db.Column(db.String(36), nullable=False)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', ondelete='CASCADE'), nullable=False, index=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    snapshot = db.deferred(db.Column(db.JSON, nullable=False))
    result = db.deferred(db.Column(db.JSON, nullable=True))
    result_hash = db.Column(db.String(64), nullable=True)
    state = db.Column(db.String(30), nullable=False, default='queued')
    progress = db.Column(db.JSON, nullable=True)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    dispatched_at = db.Column(db.DateTime, nullable=True)
    lease_until = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    applied = db.Column(db.Boolean, nullable=False, default=False)


class ExecutionUpload(db.Model):
    __tablename__ = 'execution_uploads'
    id = db.Column(db.String(36), primary_key=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(240), nullable=False)
    artifact = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ExecutionTaskFile(db.Model):
    __tablename__ = 'execution_task_files'
    id = db.Column(db.String(36), primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(240), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='attachment')
    is_public = db.Column(db.Boolean, nullable=False, default=True)
    read_only = db.Column(db.Boolean, nullable=False, default=False)
    include_in_check = db.Column(db.Boolean, nullable=False, default=False)
    artifact = db.Column(db.JSON, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
