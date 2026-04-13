import asyncio
import uuid
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="run_detection_pipeline",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
    soft_time_limit=30,
    time_limit=60,
)
def run_detection_pipeline(self: Any, event_id: str) -> dict[str, Any]:
    """Run the full detection pipeline on an ingested event.

    Called async after event ingestion returns 202 to the SDK.
    Loads the event from DB, runs detectors, persists results + incidents.

    Retries up to 3 times with exponential backoff on any failure.
    Soft timeout at 30s, hard kill at 60s.
    """
    try:
        return asyncio.run(_run_pipeline(event_id))
    except Exception:
        log.error(
            "detection.task_failed",
            event_id=event_id,
            attempt=self.request.retries + 1,
            max_retries=self.max_retries,
            exc_info=True,
        )
        raise


async def _run_pipeline(event_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import AgentEvent
    from app.db.session import make_task_session_factory
    from app.services.detection_service import run_and_persist_detections

    # Build a disposable engine + session factory for this task.
    # Celery prefork + asyncio.run() means each task runs on a fresh
    # loop, and the module-level engine would be bound to whichever
    # loop first touched it — reusing it across tasks raises
    # "Task attached to a different loop".
    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            # AgentEvent is a TimescaleDB hypertable with a composite
            # PK (id, timestamp) — session.get() rejects single-column
            # identifiers. Query by id column instead.
            result = await db.execute(
                select(AgentEvent).where(AgentEvent.id == uuid.UUID(event_id))
            )
            event = result.scalar_one_or_none()
            if event is None:
                log.warning("detection.event_not_found", event_id=event_id)
                return {"event_id": event_id, "error": "event_not_found"}

            detections = await run_and_persist_detections(db, event)
            await db.commit()

        triggered = [d for d in detections if d.triggered]

        log.info(
            "detection.completed",
            event_id=event_id,
            total_detectors=len(detections),
            triggered_count=len(triggered),
        )

        return {
            "event_id": event_id,
            "total": len(detections),
            "triggered": len(triggered),
        }
    finally:
        await task_engine.dispose()
