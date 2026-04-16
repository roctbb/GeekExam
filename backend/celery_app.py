from celery import Celery
from config import CELERY_BROKER

celery = Celery(
    'geekexam',
    broker=CELERY_BROKER,
    backend=CELERY_BROKER,
    include=['celery_tasks.check_answer'],
)

celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='Europe/Moscow',
    task_default_queue='auditor_queue',
    beat_schedule={
        'finish-expired-attempts': {
            'task': 'celery_tasks.check_answer.finish_expired_attempts',
            'schedule': 60.0,
        },
    },
)

from celery.signals import worker_ready

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    from celery_tasks.check_answer import recover_pending_answers
    recover_pending_answers.delay()
