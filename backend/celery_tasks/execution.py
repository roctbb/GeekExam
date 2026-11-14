from datetime import datetime, timedelta
from celery_app import celery


@celery.task(bind=True, max_retries=None, acks_late=True, reject_on_worker_lost=True)
def dispatch_execution(self, execution_id):
    from manage import app
    from models import db
    from execution_models import ExecutionRun
    import executor_transport as transport
    with app.app_context():
        now = datetime.utcnow()
        run = ExecutionRun.query.filter_by(id=execution_id).with_for_update().first()
        if not run or run.finished_at or run.dispatched_at or (run.lease_until and run.lease_until > now):
            db.session.rollback()
            return
        run.lease_until = now + timedelta(minutes=5)
        db.session.commit()
        try:
            if run.snapshot.get('repository'):
                from executor_repositories import capture
                capture(run)
        except ValueError as error:
            # Invalid source is terminal; preserve the immutable snapshot and an explicit result.
            from executor_service import accept_result
            value = dict(execution_id=run.id, state='execution error', points=0, comment=str(error)[:1000])
            import hashlib
            accept_result(run.id, value, hashlib.sha256(transport.json_bytes(value)).hexdigest())
            return
        except Exception as error:
            run.lease_until = None
            db.session.commit()
            raise self.retry(exc=error, countdown=60)
        try:
            transport.dispatch(run)
        except Exception as error:
            db.session.rollback()
            run = db.session.get(ExecutionRun, execution_id)
            if run and not run.finished_at: run.lease_until = None
            db.session.commit()
            raise self.retry(exc=error, countdown=min(300, 5 * 2 ** min(self.request.retries, 6)))
        run.dispatched_at = datetime.utcnow()
        run.lease_until = None
        db.session.commit()


@celery.task
def recover_executions():
    from manage import app
    from models import db
    from execution_models import ExecutionRun
    from sqlalchemy import or_
    with app.app_context():
        ids = [row.id for row in ExecutionRun.query.filter(ExecutionRun.dispatched_at.is_(None),
            ExecutionRun.finished_at.is_(None), or_(ExecutionRun.lease_until.is_(None), ExecutionRun.lease_until < datetime.utcnow()))
            .order_by(ExecutionRun.created_at).limit(100)]
        db.session.remove()
        for execution_id in ids: dispatch_execution.delay(execution_id)
