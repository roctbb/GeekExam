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


def _finalize_attempt_if_done(attempt_id, force_recalculate=False):
    """Check if all answers are checked; if so, compute total and emit WebSocket."""
    with _get_app().app_context():
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
        attempt.is_checked = True
        attempt.total_points = sum(a.points or 0 for a in answers)
        db.session.commit()

        from manage import socketio
        socketio.emit('attempt_checked', {
            'attempt_id': attempt_id,
            'total_points': attempt.total_points,
            'max_points': attempt.max_points,
        }, room=f'attempt_{attempt_id}')


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
            if not intermediate:
                _finalize_attempt_if_done(answer.attempt_id)
            return

        if is_async_check(check_type):
            checker = get_checker(check_type)
            ok = checker.submit(answer.id, answer.value or {}, question.check_config or {}, question.body, check_type, question.max_points)
            if not ok:
                answer.check_state = 'error'
                answer.check_comment = 'Ошибка отправки на проверку'
                db.session.commit()
        else:
            checker = get_checker(check_type)
            try:
                points, comment = checker.check(answer.value, question.check_config or {}, question.max_points)
                answer.points = points
                answer.check_comment = _strip_nul_chars(comment)
                answer.check_state = 'checked'
            except Exception as e:
                answer.check_state = 'error'
                answer.check_comment = _strip_nul_chars(str(e))
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


@celery.task
def check_attempt_answers(attempt_id):
    """Triggered when student finishes the test. Queues checks for all pending answers."""
    with _get_app().app_context():
        from models import Answer
        answers = Answer.query.filter_by(attempt_id=attempt_id).all()
        for answer in answers:
            if answer.check_state == 'pending' and answer.question.check_type != 'manual':
                check_single_answer.delay(answer.id)


@celery.task
def recover_pending_answers():
    """On startup: re-queue answers stuck in pending/checking for finished attempts."""
    try:
        with _get_app().app_context():
            from models import db, Answer, Attempt
            from sqlalchemy import and_
            stuck = (
                Answer.query
                .join(Attempt)
                .filter(
                    Attempt.finished_at.isnot(None),
                    Answer.check_state.in_(['pending', 'checking']),
                )
                .all()
            )
            count = 0
            for answer in stuck:
                if answer.question.check_type != 'manual':
                    answer.check_state = 'pending'
                    count += 1
            db.session.commit()
            for answer in stuck:
                if answer.question.check_type != 'manual':
                    check_single_answer.delay(answer.id)
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
            if elapsed_minutes >= attempt.test.time_limit:
                attempt.finished_at = now
                db.session.commit()
                check_attempt_answers.delay(attempt.id)
