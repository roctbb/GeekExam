from celery import Celery
from config import CELERY_BROKER

celery = Celery(
    'geekexam',
    broker=CELERY_BROKER,
    backend=CELERY_BROKER,
    include=['celery_tasks.check_answer', 'celery_tasks.execution', 'celery_tasks.presence'],
)

celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='Europe/Moscow',
    task_default_queue='auditor_queue',
    worker_prefetch_multiplier=1,
    task_routes={'celery_tasks.presence.notify': {'queue': 'notification_queue'}, 'celery_tasks.presence.*': {'queue': 'presence_queue'}},
    beat_schedule={
        'send-wifi-alerts': {'task': 'celery_tasks.presence.notify', 'schedule': 5.0},
        'collect-presence': {'task': 'celery_tasks.presence.collect', 'schedule': 5.0},
        'prune-presence-samples': {'task': 'celery_tasks.presence.prune', 'schedule': 86400.0},
        'recover-execution-outbox': {'task': 'celery_tasks.execution.recover_executions', 'schedule': 60.0},
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
