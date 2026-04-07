from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "parry",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "refresh-stale-baselines": {
            "task": "refresh_stale_baselines",
            # Run hourly — task itself decides which agents are actually stale
            "schedule": crontab(minute=0),
        },
    },
)

celery_app.autodiscover_tasks(["app.workers"])
