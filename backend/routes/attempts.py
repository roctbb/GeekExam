import random
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from auth import api_login_required, teacher_required, current_user_id, current_role
from models import db, Test, Attempt, Answer, Variant

attempts_bp = Blueprint('attempts', __name__)


def _attempt_detail(attempt, include_check_config=False):
    time_left = None
    if attempt.test.time_limit and attempt.started_at and not attempt.finished_at:
        elapsed = (datetime.utcnow() - attempt.started_at).total_seconds()
        time_left = max(0, attempt.test.time_limit * 60 - int(elapsed))

    return {
        'id': attempt.id,
        'test_id': attempt.test_id,
        'test_title': attempt.test.title,
        'variant_id': attempt.variant_id,
        'started_at': attempt.started_at.isoformat() if attempt.started_at else None,
        'finished_at': attempt.finished_at.isoformat() if attempt.finished_at else None,
        'is_checked': attempt.is_checked,
        'total_points': attempt.total_points,
        'max_points': attempt.max_points,
        'time_left': time_left,
        'questions': [
            {
                'id': q.id,
                'order': q.order,
                'type': q.type,
                'title': q.title,
                'body': q.body,
                'max_points': q.max_points,
                'check_type': q.check_type,
                'ui_config': q.ui_config,
                'allow_intermediate_check': q.allow_intermediate_check,
                **(({'check_config': q.check_config} if include_check_config else {})),
            }
            for q in attempt.variant.questions
        ],
        'answers': [
            {
                'id': a.id,
                'question_id': a.question_id,
                'value': a.value,
                'points': a.points,
                'check_state': a.check_state,
                'check_comment': a.check_comment,
            }
            for a in attempt.answers
        ],
    }


@attempts_bp.route('/api/join', methods=['POST'])
@api_login_required
def join_test():
    data = request.get_json()
    code = (data.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Введите код теста'}), 422

    test = Test.query.filter_by(code=code, is_active=True).first()
    if not test:
        return jsonify({'error': 'Тест не найден или не активен'}), 404

    user_id = current_user_id()
    # One attempt per test per student
    existing = Attempt.query.filter_by(test_id=test.id, user_id=user_id).first()
    if existing:
        return jsonify({'error': 'Вы уже проходили этот тест', 'attempt_id': existing.id}), 422

    available = test.variants

    variant = random.choice(available)
    max_points = sum(q.max_points for q in variant.questions)

    attempt = Attempt(
        test_id=test.id,
        variant_id=variant.id,
        user_id=user_id,
        max_points=max_points,
    )
    db.session.add(attempt)
    db.session.flush()

    for q in variant.questions:
        db.session.add(Answer(attempt_id=attempt.id, question_id=q.id))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Вы уже проходите этот вариант'}), 422

    return jsonify({'attempt_id': attempt.id}), 201


@attempts_bp.route('/api/attempts/<int:attempt_id>', methods=['DELETE'])
@teacher_required
def delete_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    db.session.delete(attempt)
    db.session.commit()
    return '', 204


@attempts_bp.route('/api/attempts/<int:attempt_id>', methods=['GET'])
@api_login_required
def get_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    user_id = current_user_id()
    role = current_role()
    if role not in ('teacher', 'admin') and attempt.user_id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(_attempt_detail(attempt))


@attempts_bp.route('/api/attempts/<int:attempt_id>/finish', methods=['POST'])
@api_login_required
def finish_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if attempt.finished_at:
        return jsonify({'error': 'Тест уже завершён'}), 422

    attempt.finished_at = datetime.utcnow()
    db.session.commit()

    from celery_tasks.check_answer import check_attempt_answers
    check_attempt_answers.delay(attempt_id)

    return jsonify({'status': 'finished'})


@attempts_bp.route('/api/my-attempts', methods=['GET'])
@api_login_required
def my_attempts():
    attempts = Attempt.query.filter_by(user_id=current_user_id()).order_by(Attempt.started_at.desc()).all()
    return jsonify([
        {
            'id': a.id,
            'test_id': a.test_id,
            'test_title': a.test.title,
            'variant_title': a.variant.title,
            'started_at': a.started_at.isoformat() if a.started_at else None,
            'finished_at': a.finished_at.isoformat() if a.finished_at else None,
            'is_checked': a.is_checked,
            'total_points': a.total_points,
            'max_points': a.max_points,
        }
        for a in attempts
    ])


@attempts_bp.route('/api/my-attempts/<int:attempt_id>/results', methods=['GET'])
@api_login_required
def my_attempt_results(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(_attempt_detail(attempt, include_check_config=True))
