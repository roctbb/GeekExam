"""Independent queue: Guard outages must not occupy the grading workers."""
from datetime import timedelta
import redis
from celery_app import celery
from config import CELERY_BROKER


@celery.task(name='celery_tasks.presence.collect', expires=5, ignore_result=True)
def collect():
    from manage import app
    from models import db, Attempt
    from presence_models import PresenceConfig
    from presence_service import collect_test,now
    # A renewable deployment-independent lease; never release another worker's lock.
    lock = redis.Redis.from_url(CELERY_BROKER).lock('geekexam:presence:collect', timeout=90, blocking=False)
    if not lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            ids = db.session.execute(db.select(PresenceConfig.test_id).join(Attempt, Attempt.test_id == PresenceConfig.test_id)
                .where(PresenceConfig.enabled.is_(True), db.or_(Attempt.finished_at.is_(None),Attempt.finished_at>=now()-timedelta(seconds=60))).distinct()).scalars().all()
            for test_id in ids:
                lock.extend(90, replace_ttl=True)
                try:
                    collect_test(db.session.get(PresenceConfig, test_id))
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Presence collection failed for test %s', test_id)
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


@celery.task(name='celery_tasks.presence.prune', ignore_result=True)
def prune():
    from manage import app
    from models import db, Attempt
    from presence_models import PresenceHeartbeat
    from presence_service import now
    with app.app_context():
        cutoff = now()-timedelta(days=30)
        ids = db.select(Attempt.id).where(Attempt.finished_at < cutoff)
        db.session.execute(db.delete(PresenceHeartbeat).where(PresenceHeartbeat.attempt_id.in_(ids)))
        db.session.commit()
