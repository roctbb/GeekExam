import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from copy import deepcopy
from celery_app import celery


def _get_app():
    from manage import app
    return app


def _strip_nul_chars(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul_chars(item) for item in value]
    if isinstance(value, dict):
        return {
            _strip_nul_chars(key) if isinstance(key, str) else key: _strip_nul_chars(item)
            for key, item in value.items()
        }
    return value


def _finalize_attempt_if_done_inner(attempt_id, force_recalculate=False):
    """Core finalization logic. Must be called within an active Flask app context.

    Uses an atomic UPDATE ... WHERE is_checked = FALSE to prevent double-finalization
    when multiple Celery workers call this simultaneously.
    """
    from models import db, Attempt, Answer
    attempt = Attempt.query.filter_by(id=attempt_id).populate_existing().with_for_update().first()
    if not attempt or not attempt.finished_at:
        return
    if attempt.is_checked and not force_recalculate:
        return
    answers = Answer.query.filter_by(attempt_id=attempt_id).all()
    # manual answers with pending state are not auto-checked — skip finalization until teacher grades them
    pending = [a for a in answers if a.check_state in ('pending', 'checking')]
    if pending:
        return
    total_points = sum(a.points or 0 for a in answers)

    if force_recalculate:
        # Forced recalculation (teacher grading): always update.
        updated = db.session.execute(
            db.update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(is_checked=True, total_points=total_points)
        ).rowcount
    else:
        # Normal path: only finalize once — atomic guard prevents double WS emit.
        updated = db.session.execute(
            db.update(Attempt)
            .where(Attempt.id == attempt_id, Attempt.is_checked == False)
            .values(is_checked=True, total_points=total_points)
        ).rowcount
    db.session.commit()

    if updated == 0:
        return  # Another worker already finalized this attempt.

    from manage import socketio
    socketio.emit('attempt_checked', {
        'attempt_id': attempt_id,
        'total_points': total_points,
        'max_points': attempt.max_points,
    }, room=f'attempt_{attempt_id}')


def _finalize_attempt_if_done(attempt_id, force_recalculate=False):
    """Wrapper that creates its own app context for use from Celery tasks.

    When calling from within a Flask route (which already has an app context),
    use _finalize_attempt_if_done_inner() directly to avoid nested contexts.
    """
    with _get_app().app_context():
        _finalize_attempt_if_done_inner(attempt_id, force_recalculate)


def _complete_check(answer_id, checked_value, points, comment, error=False):
    """Apply a result to its saved answer version and current attempt state."""
    from models import db
    from attempt_lifecycle import lock_answer
    from checkers.check_identity import answer_fingerprint
    from manage import socketio

    answer, attempt = lock_answer(answer_id)
    if (not answer or not attempt or answer.check_state != 'checking'
            or answer_fingerprint(answer.value) != answer_fingerprint(checked_value)):
        db.session.rollback()
        return
    finished = attempt.finished_at is not None
    comment = _strip_nul_chars(comment)
    if finished:
        answer.points = 0 if error else points
        answer.check_state = 'error' if error else 'checked'
        answer.check_comment = comment
    else:
        answer.points = None
        answer.check_state = 'pending'
        answer.check_comment = None
    attempt_id = attempt.id
    payload = {
        'answer_id': answer.id,
        'question_id': answer.question_id,
        'points': 0 if error and finished else None if error else points,
        'check_state': answer.check_state if finished else 'error' if error else 'intermediate',
        'check_comment': comment,
        'checked_value': checked_value,
    }
    db.session.commit()
    try:
        socketio.emit('answer_checked', payload, room=f'attempt_{attempt_id}')
    finally:
        if finished:
            _finalize_attempt_if_done_inner(attempt_id)


@celery.task
def check_single_answer(answer_id, intermediate=False):
    with _get_app().app_context():
        from models import db
        from attempt_lifecycle import lock_answer
        from checkers.registry import get_checker, is_async_check
        from validation import validate_answer

        answer, attempt = lock_answer(answer_id)
        if not answer or not attempt:
            return
        question = answer.question
        check_type = question.check_type
        if check_type == 'manual' or (not intermediate and not attempt.finished_at):
            return

        checked_value = deepcopy(answer.value)
        check_config = deepcopy(question.check_config or {})
        body, max_points = question.body, question.max_points
        answer.check_state = 'checking'
        answer.points = None
        answer.check_comment = None
        db.session.commit()

        try:
            validate_answer(checked_value, question)
            if checked_value is None:
                points, comment = 0, 'Ответ не предоставлен'
            elif is_async_check(check_type):
                result = get_checker(check_type).submit(
                    answer_id, checked_value, check_config, body, check_type, max_points,
                )
                ok, message = result if isinstance(result, tuple) else (bool(result), None)
                if ok:
                    return  # The callback applies the result to the current attempt state.
                raise ValueError(message or 'Ошибка отправки на проверку')
            else:
                points, comment = get_checker(check_type).check(checked_value, check_config, max_points)
                if type(points) is not int or not 0 <= points <= max_points:
                    raise ValueError('Проверяющая программа вернула недопустимый балл')
                if comment is not None and not isinstance(comment, str):
                    raise ValueError('Проверяющая программа вернула недопустимый комментарий')
        except Exception as e:
            db.session.rollback()
            _complete_check(answer_id, checked_value, None, str(e), error=True)
            return
        _complete_check(answer_id, checked_value, points, comment)


@celery.task
def check_attempt_answers(attempt_id):
    """Queue pending answers; in-flight checks finalize against finished_at."""
    with _get_app().app_context():
        from models import db, Answer, Attempt
        attempt = Attempt.query.filter_by(id=attempt_id).with_for_update().first()
        if not attempt or not attempt.finished_at:
            return
        answers = Answer.query.filter_by(attempt_id=attempt_id).with_for_update().all()
        to_check = []
        for answer in answers:
            if answer.question.check_type == 'manual' or answer.check_state != 'pending':
                continue
            answer.points = None
            answer.check_comment = None
            to_check.append(answer.id)
        db.session.commit()
        for answer_id in to_check:
            check_single_answer.delay(answer_id)
        _finalize_attempt_if_done_inner(attempt_id)


@celery.task
def recover_pending_answers():
    """On startup: re-queue answers stuck in pending for finished attempts.

    Only recovers answers in 'pending' state — 'checking' means an async job
    was already submitted to GeekPaste and a callback is expected; re-queuing
    those would create duplicate tasks.  If the callback never arrives they will
    remain stuck until manual intervention or the next restart, which is the
    safer failure mode.
    """
    try:
        with _get_app().app_context():
            from models import db, Answer, Attempt
            stuck = (
                Answer.query
                .join(Attempt)
                .filter(
                    Attempt.finished_at.isnot(None),
                    Answer.check_state == 'pending',
                )
                .all()
            )
            count = 0
            to_queue = []
            for answer in stuck:
                if answer.question.check_type != 'manual':
                    to_queue.append(answer.id)
                    count += 1
            # No state change needed — already 'pending'.
            for answer_id in to_queue:
                check_single_answer.delay(answer_id)
            print(f'[recover] Re-queued {count} stuck answers')
    except Exception as e:
        print(f'[recover] Skipped: {e}')


@celery.task
def finish_expired_attempts():
    """Celery-beat task: auto-finish attempts where time_limit has expired."""
    with _get_app().app_context():
        from models import db, Attempt, Test
        from attempt_lifecycle import finish_if_expired
        now = datetime.utcnow()
        active_ids = (
            db.session.query(Attempt.id).join(Test)
            .filter(Attempt.finished_at.is_(None), Test.time_limit.isnot(None)).all()
        )
        for (attempt_id,) in active_ids:
            try:
                attempt = Attempt.query.filter_by(id=attempt_id).populate_existing().with_for_update().first()
                if not attempt or not finish_if_expired(attempt, now):
                    db.session.rollback()
            except Exception as e:
                db.session.rollback()
                print(f'[finish_expired] Failed to finish attempt {attempt_id}: {e}')
