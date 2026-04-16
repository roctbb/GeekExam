from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)


class Test(db.Model):
    __tablename__ = 'tests'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    code = db.Column(db.String(50), unique=True, nullable=True)
    time_limit = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source_json = db.Column(db.Text, nullable=True)

    variants = db.relationship('Variant', backref='test', cascade='all, delete-orphan', order_by='Variant.order')
    creator = db.relationship('User', backref='tests')


class Variant(db.Model):
    __tablename__ = 'variants'
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    order = db.Column(db.Integer, default=0)

    questions = db.relationship('Question', backref='variant', cascade='all, delete-orphan', order_by='Question.order')


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('variants.id'), nullable=False)
    order = db.Column(db.Integer, default=0)
    type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    max_points = db.Column(db.Integer, nullable=False)
    check_type = db.Column(db.String(50), nullable=False)
    check_config = db.Column(db.JSON, nullable=True)
    ui_config = db.Column(db.JSON, nullable=True)
    allow_intermediate_check = db.Column(db.Boolean, default=False, nullable=False)


class Attempt(db.Model):
    __tablename__ = 'attempts'
    __table_args__ = (db.UniqueConstraint('user_id', 'variant_id', name='uq_user_variant'),)

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('variants.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_checked = db.Column(db.Boolean, default=False, nullable=False)
    total_points = db.Column(db.Integer, nullable=True)
    max_points = db.Column(db.Integer, nullable=False)

    test = db.relationship('Test', backref='attempts')
    variant = db.relationship('Variant', backref='attempts')
    user = db.relationship('User', backref='attempts')
    answers = db.relationship('Answer', backref='attempt', cascade='all, delete-orphan', passive_deletes=True)


class Answer(db.Model):
    __tablename__ = 'answers'
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('attempts.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    value = db.Column(db.JSON, nullable=True)
    points = db.Column(db.Integer, nullable=True)
    check_state = db.Column(db.String(20), default='pending', nullable=False)
    check_comment = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    question = db.relationship('Question', backref='answers')
