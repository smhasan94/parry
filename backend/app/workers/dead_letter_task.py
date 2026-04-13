"""Dead letter sink — captures tasks that exhausted all retries.

Messages land here via the ParryTask.on_failure handler. This task
simply logs the failure with full context so ops can audit and replay.
No automatic retry — these are permanently failed tasks by definition.
"""

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="dead_letter_sink",
    max_retries=0,
    queue="dead_letter",
)
def dead_letter_sink(
    original_task: str,
    task_id: str,
    args: list | None = None,
    kwargs: dict | None = None,
    exception: str = "",
    retries: int = 0,
) -> dict:
    """Persist a dead-lettered task for auditing.

    Currently logs at ERROR level. Future: write to a DB table
    or push to an alerting channel for manual review/replay.
    """
    log.error(
        "dead_letter.received",
        original_task=original_task,
        original_task_id=task_id,
        original_args=args,
        original_kwargs=kwargs,
        exception=exception,
        retries_exhausted=retries,
    )
    return {
        "original_task": original_task,
        "task_id": task_id,
        "exception": exception,
        "retries": retries,
    }
