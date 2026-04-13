import structlog
from celery import Celery, Task
from celery.schedules import crontab

from app.core.config import settings

log = structlog.get_logger()


class ParryTask(Task):
    """Base task that routes permanently-failed tasks to the dead letter queue."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[no-untyped-def]
        # Only send to DLQ after all retries are exhausted
        if self.request.retries >= self.max_retries:
            try:
                self.app.send_task(
                    "dead_letter_sink",
                    queue="dead_letter",
                    kwargs={
                        "original_task": self.name,
                        "task_id": task_id,
                        "args": args,
                        "kwargs": kwargs,
                        "exception": str(exc),
                        "retries": self.request.retries,
                    },
                )
                log.warning(
                    "task.dead_lettered",
                    task_name=self.name,
                    task_id=task_id,
                    retries=self.request.retries,
                    exception=str(exc),
                )
            except Exception:
                log.error(
                    "task.dead_letter_failed",
                    task_name=self.name,
                    task_id=task_id,
                    exc_info=True,
                )
        super().on_failure(exc, task_id, args, kwargs, einfo)

celery_app = Celery(
    "parry",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    task_cls=ParryTask,
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
        "app.workers.supplier_refresh_task",
        "app.workers.auditor_bundle_task",
        "app.workers.compliance_refresh_task",
        "app.workers.threat_intel_task",
        "app.workers.webhook_delivery_task",
        "app.workers.scheduled_report_task",
        "app.workers.digest_task",
        "app.workers.dead_letter_task",
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
    # Global timeouts — individual tasks can override via decorator args.
    # soft_time_limit raises SoftTimeLimitExceeded (catchable, allows cleanup).
    # task_time_limit kills the worker process (last resort).
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=360,  # 6 minutes (hard kill)
    task_reject_on_worker_lost=True,  # requeue if worker crashes mid-task
    worker_max_tasks_per_child=200,  # restart worker process after 200 tasks (leak prevention)
    # Result TTL — auto-expire results after 1 hour to prevent unbounded Redis growth
    result_expires=3600,
    # Dead letter queue — tasks that exhaust all retries get routed here
    # instead of silently vanishing. Workers on the default queue ignore
    # DLQ messages; a separate consumer or periodic audit reads them.
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "dead_letter": {"exchange": "dead_letter", "routing_key": "dead_letter"},
    },
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
        "compliance-daily-refresh": {
            "task": "compliance_refresh",
            # Daily at 03:00 UTC — after metered usage, before supplier refresh.
            "schedule": crontab(hour=3, minute=0),
        },
        "send-due-reports": {
            "task": "send_due_reports",
            # Hourly check for due scheduled reports.
            "schedule": crontab(minute=30),
        },
        "threat-intel-decay": {
            "task": "threat_intel_decay",
            # Daily at 05:00 UTC — after compliance refresh.
            "schedule": crontab(hour=5, minute=0),
        },
        "refresh-supplier-register": {
            "task": "refresh_supplier_register",
            # Daily at 04:00 UTC — after audit export, before business hours.
            "schedule": crontab(hour=4, minute=0),
        },
        "send-weekly-digest": {
            "task": "send_weekly_digest",
            # Monday at 09:00 UTC — start of the work week.
            "schedule": crontab(hour=9, minute=0, day_of_week=1),
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
