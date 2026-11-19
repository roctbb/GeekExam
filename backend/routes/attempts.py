from time_utils import utc_iso
import random
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from math import isclose

from auth import api_login_required, teacher_required, current_user_id, current_role
from models import db, Test, Attempt, Answer, Variant
from checkers.check_types.exact import normalize_text
from attempt_lifecycle import finish_locked_attempt
from presence_models import PresenceConfig
import guard_admission as guard

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

        value = answer.value if isinstance(answer.value, dict) else {}
        check_config = question.check_config or {}

        items = []
        if question.check_type == 'exact' and question.type == 'multi_input' and isinstance(check_config.get('answers'), dict):
            correct = check_config['answers']
            fields = (question.ui_config or {}).get('fields') or []
            fields_by_name = {field.get('name'): field for field in fields if isinstance(field, dict)}
            for key, expected in correct.items():
                field = fields_by_name.get(key, {'name': key})
                got = normalize_text(value.get(key, ''), check_config)
                exp = normalize_text(expected, check_config)
                is_correct = got == exp
                items.append((_topic_from_field(question, field), is_correct))

        if question.check_type == 'exact' and question.type == 'true_false_table' and isinstance(check_config.get('correct'), list):
            correct = check_config['correct']
            given = value.get('answers') or []
            for index, expected in enumerate(correct):
                is_correct = index < len(given) and given[index] == expected
                items.append((_topic_from_index(question, 'statement_topics', index), is_correct))

        if question.check_type == 'exact' and question.type == 'choice_table' and isinstance(check_config.get('correct'), list):
            correct = check_config['correct']
            given = value.get('answers') or []
            for index, expected in enumerate(correct):
                is_correct = index < len(given) and given[index] == expected
                items.append((_topic_from_choice_item(question, index), is_correct))

        # Only split a recorded grade when the field-level allocation is exact.
        # All-or-nothing grading, rounding and teacher overrides cannot be
        # reliably attributed to individual fields; report those at question level.
        if items and check_config.get('partial_scoring', True):
            item_max = question.max_points / len(items)
            if isclose(item_max * sum(correct for _, correct in items), answer.points, abs_tol=1e-9):
                for topic, correct in items:
                    _add_topic_stat(stats, topic, item_max if correct else 0, item_max, correct)
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
    from executor_service import execution_links
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
            'files_url': f'/api/attempts/{attempt.id}/questions/{q.id}/files',
        }
        if q.check_type in ('ai', 'docker', 'manual'):
            cfg = q.check_config or {}
            question['submission_config'] = {key: cfg[key] for key in ('lang','allowed_languages','submission_modes',
                'allowed_extensions','entrypoint','max_files','max_file_bytes','max_total_bytes') if key in cfg}
            public = question['submission_config']
            from executor_validation import default_language
            public.setdefault('lang', default_language(q.check_type, cfg, q.ui_config))
            public.setdefault('allowed_languages', [public['lang']])
            public.setdefault('submission_modes', ['files','code','project','repository'] if q.type in ('code_input','interactive') else ['text','files'])
        if include_check_config:
            if current_role() in ('teacher', 'admin'):
                question['check_config'] = q.check_config
            else:
                from executor_service import public_check_config
                question['check_config'] = public_check_config(q)
        questions.append(question)

    return {
        'id': attempt.id,
        'test_id': attempt.test_id,
        'test_title': attempt.test.title,
        'variant_id': attempt.variant_id,
        'guard_required': guard.requires_guard(db.session.get(PresenceConfig, attempt.test_id)),
        'started_at': utc_iso(attempt.started_at),
        'finished_at': utc_iso(attempt.finished_at),
        'is_checked': attempt.is_checked,
        'total_points': attempt.total_points,
        'max_points': attempt.max_points,
        'time_left': time_left,
        'server_time': utc_iso(server_now),
        'time_deadline_at': utc_iso(time_deadline_at),
        'questions': questions,
        'answers': [
            {
                'id': a.id,
                'question_id': a.question_id,
                'value': a.value,
                'points': a.points,
                'check_state': ('error' if not attempt.finished_at and a.check_state == 'pending'
                                and a.check_comment else a.check_state),
                'check_comment': a.check_comment,
            }
            for a in attempt.answers
        ],
        'topic_summary': _topic_summary(attempt),
        'executions': execution_links(attempt.id, current_user_id(), attempt.answers),
    }


@attempts_bp.route('/api/join', methods=['POST'])
@api_login_required
def join_test():
    data = request.get_json(silent=True)
    code = data.get('code') if isinstance(data, dict) else None
    code = code.strip().upper() if isinstance(code, str) else ''
    if not code:
        return jsonify({'error': 'Введите код теста'}), 422

    # Serialize admission with teacher stop: no attempt may start after the
    # stop transaction has finished all existing attempts.
    test = Test.query.filter_by(code=code, is_active=True).with_for_update().first()
    if not test:
        return jsonify({'error': 'Тест не найден или не активен'}), 404

    user_id = current_user_id()
    # One attempt per test per student
    existing = Attempt.query.filter_by(test_id=test.id, user_id=user_id).first()
    config = db.session.get(PresenceConfig, test.id)
    if existing and (existing.finished_at or not guard.requires_guard(config)):
        return jsonify({'error': 'Вы уже проходили этот тест', 'attempt_id': existing.id}), 422

    admission = None
    if guard.requires_guard(config):
        admission = guard.Admission.for_test(test, config, user_id)
        if 'guard_ticket' not in data and 'proof_ids' not in data:
            return guard.start_proof(admission)
        candidate, proof_id = guard.consume_proof(admission, data.get('guard_ticket'), data.get('proof_ids'))
        test = Test.query.filter_by(id=admission.test_id, code=code, is_active=True).with_for_update().first()
        if not test:
            return jsonify(error='Тест не найден или не активен'), 404
        config = db.session.get(PresenceConfig, test.id)
        if not guard.requires_guard(config) or guard.Admission.for_test(test, config, user_id) != admission:
            return guard.admission_error('Настройки доступа изменились. Войдите в тест ещё раз.', 409)
        existing = Attempt.query.filter_by(test_id=test.id, user_id=user_id).with_for_update().first()
        if existing:
            if existing.finished_at:
                return jsonify(error='Вы уже проходили этот тест', attempt_id=existing.id), 422
            guard.record_binding(existing, admission, candidate, proof_id)
            db.session.commit()
            guard.remember_admission(existing, admission, candidate)
            return jsonify(attempt_id=existing.id)

    available = test.variants
    if not available or any(not variant.questions for variant in available):
        return jsonify({'error': 'Тест не содержит вариантов с вопросами'}), 422

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
        if admission:
            guard.record_binding(attempt, admission, candidate, proof_id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Вы уже проходите этот вариант'}), 422

    if admission:
        guard.remember_admission(attempt, admission, candidate)
    from socket_events import publish_attempt_change
    publish_attempt_change(attempt)
    return jsonify({'attempt_id': attempt.id}), 201


@attempts_bp.route('/api/attempts/<int:attempt_id>', methods=['DELETE'])
@teacher_required
def delete_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    db.session.delete(attempt)
    db.session.commit()
    from socket_events import publish_attempt_change
    publish_attempt_change(attempt)
    return '', 204


@attempts_bp.route('/api/attempts/<int:attempt_id>', methods=['GET'])
@api_login_required
def get_attempt(attempt_id):
    attempt = Attempt.query.get_or_404(attempt_id)
    user_id = current_user_id()
    role = current_role()
    if role not in ('teacher', 'admin') and attempt.user_id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    if role not in ('teacher', 'admin') and not guard.attempt_access_allowed(attempt):
        return guard.admission_error()
    return jsonify(_attempt_detail(attempt, include_check_config=role in ('teacher', 'admin')))


@attempts_bp.route('/api/attempts/<int:attempt_id>/finish', methods=['POST'])
@api_login_required
def finish_attempt(attempt_id):
    attempt = Attempt.query.filter_by(id=attempt_id).with_for_update().first_or_404()
    if attempt.user_id != current_user_id():
        return jsonify({'error': 'Forbidden'}), 403
    if not guard.attempt_access_allowed(attempt):
        return guard.admission_error()

    if not finish_locked_attempt(attempt):
        return jsonify({'error': 'Тест уже завершён'}), 422

    from executor_service import execution_links
    return jsonify(status='finished', executions=execution_links(attempt.id, attempt.user_id))


@attempts_bp.route('/api/attempts/<int:attempt_id>/recheck', methods=['POST'])
@teacher_required
def recheck_attempt(attempt_id):
    attempt = Attempt.query.filter_by(id=attempt_id).with_for_update().first_or_404()
    if not attempt.finished_at:
        return jsonify({'error': 'Перепроверка доступна только для завершённых работ'}), 422

    from executor_service import submit, execution_links, publish_created
    from celery_tasks.check_answer import check_single_answer
    queued, local, native = [], [], []
    try:
        for answer in attempt.answers:
            question = answer.question
            if question.check_type == 'manual' or answer.check_state == 'checking': continue
            if question.check_type in ('ai', 'docker'):
                before = answer.latest_execution_id
                submit(answer.id, answer.value, question.check_config, question.body, question.check_type, question.max_points, commit=False)
                if answer.latest_execution_id != before: native.append(answer.latest_execution_id)
            else:
                answer.check_state = 'checking'
                local.append(answer.id)
            queued.append(answer.id)
        if not queued: return jsonify(error='Нет ответов для автоматической перепроверки'), 422
        attempt.is_checked = False
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify(error=str(error)), 422
    for run_id in native: publish_created(run_id)
    for answer_id in local: check_single_answer.delay(answer_id, intermediate=False)
    return jsonify(status='checking', queued=len(queued), executions=execution_links(attempt.id, attempt.user_id))


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
            'started_at': utc_iso(a.started_at),
            'finished_at': utc_iso(a.finished_at),
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
    if not attempt.finished_at:
        return jsonify({'error': 'Результаты доступны после завершения теста'}), 422
    return jsonify(_attempt_detail(attempt, include_check_config=True))
