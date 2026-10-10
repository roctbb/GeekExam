from time_utils import utc_iso
from datetime import datetime, timedelta

from models import db, Answer, Attempt


def attempt_deadline(attempt):
    if attempt.test.time_limit is not None and attempt.started_at is not None:
        return attempt.started_at + timedelta(minutes=attempt.test.time_limit)
    return None


def lock_answer(answer_id):
    """Lock the parent before the answer, consistently with finishing/grading."""
    answer = db.session.get(Answer, answer_id)
    if answer is None:
        return None, None
    attempt = Attempt.query.filter_by(id=answer.attempt_id).populate_existing().with_for_update().first()
    answer = Answer.query.filter_by(id=answer_id).populate_existing().with_for_update().first()
    return answer, attempt


def finish_locked_attempt(attempt, now=None):
    """Caller holds the attempt lock. Commit before publishing the Celery task."""
    if attempt.finished_at is not None:
        return False
    now = now or datetime.utcnow()
    deadline = attempt_deadline(attempt)
    attempt.finished_at = min(now, deadline) if deadline else now
    attempt.is_checked = False
    attempt.total_points = None
    attempt_id, finished_at = attempt.id, utc_iso(attempt.finished_at)
    db.session.commit()
    from celery_tasks.check_answer import check_attempt_answers
    check_attempt_answers.delay(attempt_id)
    from manage import socketio
    socketio.emit('attempt_finished', {'attempt_id': attempt_id, 'finished_at': finished_at},
                  room=f'attempt_{attempt_id}')
    return True


def finish_if_expired(attempt, now=None):
    now = now or datetime.utcnow()
    deadline = attempt_deadline(attempt)
    if attempt.finished_at is None and deadline is not None and now >= deadline:
        return finish_locked_attempt(attempt, now)
    return False
