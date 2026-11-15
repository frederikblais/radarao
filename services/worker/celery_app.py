from celery import Celery

from api.app.config import get_settings

settings = get_settings()
app = Celery("radarao", broker=settings.redis_url, backend=settings.redis_url, include=["worker.tasks"])
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "worker.tasks.analyze_dossier": {"queue": "analysis"},
        "worker.tasks.answer_question": {"queue": "analysis"},
    },
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    timezone="America/Toronto",
    broker_connection_retry_on_startup=True,
    # Planification : en production, ce sont des CronJobs Kubernetes (infra/k8s); beat sert au dev local.
    beat_schedule={
        "ingestion-hebdo": {"task": "worker.tasks.ingest_latest", "schedule": 6 * 3600},
        "purge-loi25": {"task": "worker.tasks.purge_expired", "schedule": 24 * 3600},
    },
)
