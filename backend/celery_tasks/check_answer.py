import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
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
    attempt = Attempt.query.get(attempt_id)
    if not attempt:
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


@celery.task
def check_single_answer(answer_id, intermediate=False):
    with _get_app().app_context():
        from models import db, Answer
        from checkers.registry import get_checker, is_async_check

        answer = Answer.query.get(answer_id)
        if not answer:
            return

        question = answer.question
        check_type = question.check_type

        if check_type == 'manual':
            return

        answer.check_state = 'checking'
        db.session.commit()

        # No answer provided — give 0 immediately
        if answer.value is None:
            answer.points = 0
            answer.check_state = 'checked'
            answer.check_comment = 'Ответ не предоставлен'
            db.session.commit()

            from manage import socketio
            socketio.emit('answer_checked', {
                'answer_id': answer.id,
                'question_id': answer.question_id,
                'points': answer.points,
                'check_state': answer.check_state,
                'check_comment': answer.check_comment,
            }, room=f'attempt_{answer.attempt_id}')

            if not intermediate:
                _finalize_attempt_if_done(answer.attempt_id)
            return

        if is_async_check(check_type):
            checker = get_checker(check_type)
            submit_result = checker.submit(
                answer.id,
                answer.value or {},
                question.check_config or {},
                question.body,
                check_type,
                question.max_points,
            )
            if isinstance(submit_result, tuple):
                ok, error_message = submit_result
            else:
                ok, error_message = bool(submit_result), None
            if not ok:
                if intermediate:
                    # Don't permanently mark as error for intermediate checks —
                    # restore pending so the answer is still checked on finish.
                    answer.check_state = 'pending'
                else:
                    answer.check_state = 'error'
                    answer.check_comment = error_message or 'Ошибка отправки на проверку'
                db.session.commit()

                from manage import socketio
                socketio.emit('answer_checked', {
                    'answer_id': answer.id,
                    'question_id': answer.question_id,
                    'points': answer.points,
                    'check_state': 'error',
                    'check_comment': error_message or 'Ошибка отправки на проверку',
                }, room=f'attempt_{answer.attempt_id}')
        else:
            checker = get_checker(check_type)
            try:
                points, comment = checker.check(answer.value, question.check_config or {}, question.max_points)
                if intermediate:
                    # For intermediate checks: send result via WS only, do NOT
                    # persist points — answer must be re-evaluated on final submit.
                    answer.check_state = 'pending'
                    db.session.commit()
                    from manage import socketio
                    socketio.emit('answer_checked', {
                        'answer_id': answer.id,
                        'question_id': answer.question_id,
                        'points': points,
                        'check_state': 'intermediate',
                        'check_comment': _strip_nul_chars(comment),
                    }, room=f'attempt_{answer.attempt_id}')
                else:
                    answer.points = points
                    answer.check_comment = _strip_nul_chars(comment)
                    answer.check_state = 'checked'
                    db.session.commit()
                    from manage import socketio
                    socketio.emit('answer_checked', {
                        'answer_id': answer.id,
                        'question_id': answer.question_id,
                        'points': answer.points,
                        'check_state': answer.check_state,
                        'check_comment': answer.check_comment,
                    }, room=f'attempt_{answer.attempt_id}')
                    _finalize_attempt_if_done(answer.attempt_id)
            except Exception as e:
                answer.check_state = 'error' if not intermediate else 'pending'
                answer.check_comment = _strip_nul_chars(str(e)) if not intermediate else answer.check_comment
                db.session.commit()
                from manage import socketio
                socketio.emit('answer_checked', {
                    'answer_id': answer.id,
                    'question_id': answer.question_id,
                    'points': None,
                    'check_state': 'error',
                    'check_comment': _strip_nul_chars(str(e)),
                }, room=f'attempt_{answer.attempt_id}')


@celery.task
def check_attempt_answers(attempt_id):
    """Triggered when student finishes the test. Queues checks for all non-manual answers.

    We reset 'checked' and 'error' answers back to 'pending' so that any answer
    that was intermediate-checked (and thus already 'checked') is properly
    re-evaluated against the final submitted value.
    Answers currently 'checking' (async job in flight) are left alone — the
    callback will handle them.
    """
    with _get_app().app_context():
        from models import db, Answer
        answers = Answer.query.filter_by(attempt_id=attempt_id).all()
        to_check = []
        for answer in answers:
            if answer.question.check_type == 'manual':
                continue
            if answer.check_state == 'checking':
                # Async job already submitted; callback will finalize.
                continue
            # Reset so the definitive check runs regardless of prior intermediate result.
            answer.check_state = 'pending'
            answer.points = None
            answer.check_comment = None
            to_check.append(answer.id)
        db.session.commit()
        for answer_id in to_check:
            check_single_answer.delay(answer_id)


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
        from sqlalchemy import and_
        now = datetime.utcnow()
        active = (
            Attempt.query
            .join(Test)
            .filter(
                and_(
                    Attempt.finished_at.is_(None),
                    Test.time_limit.isnot(None),
                )
            )
            .all()
        )
        for attempt in active:
            elapsed_minutes = (now - attempt.started_at).total_seconds() / 60
            if elapsed_minutes < attempt.test.time_limit:
                continue
            try:
                # Atomic finish — same guard as the HTTP endpoint.
                updated = db.session.execute(
                    db.update(Attempt)
                    .where(Attempt.id == attempt.id, Attempt.finished_at.is_(None))
                    .values(finished_at=now)
                ).rowcount
                db.session.commit()
                if updated:
                    check_attempt_answers.delay(attempt.id)
            except Exception as e:
                db.session.rollback()
                print(f'[finish_expired] Failed to finish attempt {attempt.id}: {e}')
