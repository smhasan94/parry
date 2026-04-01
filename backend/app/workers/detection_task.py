import asyncio
import uuid

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="run_detection_pipeline")
def run_detection_pipeline(event_id: str) -> dict:
    """Run the full detection pipeline on an ingested event.

    Called async after event ingestion returns 202 to the SDK.
    Loads the event from DB, runs detectors, persists results + incidents.
    """
    return asyncio.run(_run_pipeline(event_id))


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
