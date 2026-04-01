import asyncio
import uuid

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="run_detection_pipeline",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
    soft_time_limit=30,
    time_limit=60,
)
def run_detection_pipeline(self, event_id: str) -> dict:  # type: ignore[no-untyped-def]
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


async def _run_pipeline(event_id: str) -> dict:
    from app.db.models import AgentEvent
    from app.db.session import async_session_factory
    from app.services.detection_service import run_and_persist_detections

    async with async_session_factory() as db:
        event = await db.get(AgentEvent, uuid.UUID(event_id))
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
