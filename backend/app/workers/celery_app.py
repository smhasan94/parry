from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "parry",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Explicit includes — autodiscover_tasks looks for `tasks.py` per
    # package, but our worker modules are named *_task.py so nothing
    # would be registered. Missing any entry here means the task
    # silently never runs. This was a real bug in production:
    # run_detection_pipeline was being enqueued on every event
    # ingest and the worker was rejecting it as "unregistered task."
    include=[
        "app.workers.detection_task",
        "app.workers.baseline_refresh_task",
        "app.workers.health_score_task",
        "app.workers.metered_usage_task",
        "app.workers.audit_export_task",
        "app.workers.red_team_task",
    ],
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
        "refresh-health-scores": {
            "task": "refresh_health_scores",
            # Hourly, offset 15 minutes so it doesn't contend with the
            # baseline refresh run.
            "schedule": crontab(minute=15),
        },
        "report-metered-usage": {
            "task": "report_metered_usage",
            # Daily at 01:00 UTC — well outside any dashboard/user peak.
            "schedule": crontab(hour=1, minute=0),
        },
        "export-audit-log-monthly": {
            "task": "export_audit_log_monthly",
            # 1st of every month at 02:00 UTC — covers the previous
            # full calendar month.
            "schedule": crontab(hour=2, minute=0, day_of_month=1),
        },
    },
)

# NOTE: we previously also called celery_app.autodiscover_tasks(
# ["app.workers"]) here but it's ineffective for this module layout
# (no tasks.py files) and only served to mask the real bug. Task
# registration now happens exclusively via the include= list above.
