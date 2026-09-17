import random
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from auth import api_login_required, teacher_required, current_user_id, current_role
from models import db, Test, Attempt, Answer, Variant
from checkers.check_types.exact import normalize_text

attempts_bp = Blueprint('attempts', __name__)


def _topic_from_question(question):
    ui_config = question.ui_config or {}
    return ui_config.get('topic') or question.title or 'Без темы'


def _topic_from_field(question, field):
    ui_config = question.ui_config or {}
    field_topics = ui_config.get('field_topics') or {}
    name = field.get('name')
    return field.get('topic') or field_topics.get(name) or _topic_from_question(question)


def _topic_from_index(question, key, index):
    ui_config = question.ui_config or {}
    topics = ui_config.get(key) or []
    if isinstance(topics, list) and index < len(topics):
        return topics[index] or _topic_from_question(question)
    if isinstance(topics, dict):
        return topics.get(str(index)) or topics.get(index) or _topic_from_question(question)
    return _topic_from_question(question)


def _topic_from_choice_item(question, index):
    ui_config = question.ui_config or {}
    items = ui_config.get('items') or []
    if index < len(items) and isinstance(items[index], dict):
        return items[index].get('topic') or _topic_from_index(question, 'item_topics', index)
    return _topic_from_index(question, 'item_topics', index)


def _add_topic_stat(stats, topic, points, max_points, correct=None):
    topic = topic or 'Без темы'
    row = stats.setdefault(topic, {'topic': topic, 'points': 0, 'max_points': 0, 'correct': 0, 'total': 0})
    row['points'] += points
    row['max_points'] += max_points
    if correct is not None:
        row['correct'] += 1 if correct else 0
        row['total'] += 1


def _topic_summary(attempt):
    answers_by_question = {answer.question_id: answer for answer in attempt.answers}
    stats = {}

    for question in attempt.variant.questions:
        answer = answers_by_question.get(question.id)
        if not answer or answer.check_state != 'checked' or answer.points is None:
            continue

        value = answer.value or {}
        check_config = question.check_config or {}

        if question.check_type == 'exact' and question.type == 'multi_input' and isinstance(check_config.get('answers'), dict):
            correct = check_config['answers']
            fields = (question.ui_config or {}).get('fields') or []
            fields_by_name = {field.get('name'): field for field in fields if isinstance(field, dict)}
            item_max = question.max_points / max(len(correct), 1)
            for key, expected in correct.items():
                field = fields_by_name.get(key, {'name': key})
                got = normalize_text(value.get(key, ''), check_config)
                exp = normalize_text(expected, check_config)
                is_correct = got == exp
                _add_topic_stat(stats, _topic_from_field(question, field), item_max if is_correct else 0, item_max, is_correct)
            continue

        if question.check_type == 'exact' and question.type == 'true_false_table' and isinstance(check_config.get('correct'), list):
            correct = check_config['correct']
            given = value.get('answers') or []
            item_max = question.max_points / max(len(correct), 1)
            for index, expected in enumerate(correct):
                is_correct = index < len(given) and given[index] == expected
                _add_topic_stat(stats, _topic_from_index(question, 'statement_topics', index), item_max if is_correct else 0, item_max, is_correct)
            continue

        if question.check_type == 'exact' and question.type == 'choice_table' and isinstance(check_config.get('correct'), list):
            correct = check_config['correct']
            given = value.get('answers') or []
            item_max = question.max_points / max(len(correct), 1)
            for index, expected in enumerate(correct):
                is_correct = index < len(given) and given[index] == expected
                _add_topic_stat(stats, _topic_from_choice_item(question, index), item_max if is_correct else 0, item_max, is_correct)
            continue

        # Use the recorded grade for single answers, including teacher overrides.
        # Re-comparing with the reference here would undo manual grading in the summary.
        points = answer.points or 0
        _add_topic_stat(stats, _topic_from_question(question), points, question.max_points, points >= question.max_points)

    summary = []
    for row in stats.values():
        percent = (row['points'] / row['max_points'] * 100) if row['max_points'] else 0
        summary.append({
            'topic': row['topic'],
            'points': round(row['points'], 2),
            'max_points': round(row['max_points'], 2),
            'percent': round(percent),
            'correct': row['correct'],
            'total': row['total'],
        })
    # Compare numbers within topic names numerically: «Тема 2» before «Тема 10».
    summary.sort(key=lambda item: [
        int(part) if index % 2 else part.casefold()
        for index, part in enumerate(re.split(r'(\d+)', str(item['topic'])))
    ])
    return summary


def _attempt_detail(attempt, include_check_config=False):
    server_now = datetime.utcnow()
    time_left = None
    time_deadline_at = None
    if attempt.test.time_limit and attempt.started_at:
        time_deadline_at = attempt.started_at + timedelta(minutes=attempt.test.time_limit)
        if not attempt.finished_at:
            time_left = max(0, int((time_deadline_at - server_now).total_seconds()))

    questions = []
    for q in attempt.variant.questions:
        question = {
            'id': q.id,
            'order': q.order,
            'type': q.type,
            'title': q.title,
            'body': q.body,
            'max_points': q.max_points,
            'check_type': q.check_type,
            'ui_config': q.ui_config,
            'allow_intermediate_check': q.allow_intermediate_check,
        }
        if include_check_config:
            question['check_config'] = q.check_config
        questions.append(question)

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
        'server_time': server_now.isoformat() + 'Z',
        'time_deadline_at': time_deadline_at.isoformat() + 'Z' if time_deadline_at else None,
        'questions': questions,
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
        'topic_summary': _topic_summary(attempt),
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

    # Atomic update: only set finished_at when it is still NULL.
    # Prevents double-finalization from concurrent requests (e.g. timer + button).
    now = datetime.utcnow()
    updated = (
        db.session.execute(
            db.update(Attempt)
            .where(Attempt.id == attempt_id, Attempt.finished_at.is_(None))
            .values(finished_at=now)
        ).rowcount
    )
    db.session.commit()
    if updated == 0:
        return jsonify({'error': 'Тест уже завершён'}), 422

    from celery_tasks.check_answer import check_attempt_answers
    check_attempt_answers.delay(attempt_id)

    return jsonify({'status': 'finished'})


@attempts_bp.route('/api/attempts/<int:attempt_id>/recheck', methods=['POST'])
@teacher_required
def recheck_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    if not attempt.finished_at:
        return jsonify({'error': 'Перепроверка доступна только для завершённых работ'}), 422

    to_check = []
    for answer in attempt.answers:
        if answer.question.check_type == 'manual':
            continue
        if answer.check_state == 'checking':
            continue
        answer.check_state = 'checking'
        answer.points = None
        answer.check_comment = None
        to_check.append(answer.id)

    if not to_check:
        return jsonify({'error': 'Нет ответов для автоматической перепроверки'}), 422

    attempt.is_checked = False
    attempt.total_points = None
    db.session.commit()

    from celery_tasks.check_answer import check_single_answer
    for answer_id in to_check:
        check_single_answer.delay(answer_id, intermediate=False)

    return jsonify({'status': 'checking', 'queued': len(to_check)})


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
