import asyncio
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="run_detection_pipeline")
def run_detection_pipeline(event_id: str, event_data: dict[str, Any]) -> dict[str, Any]:
    """Run the full detection pipeline on an ingested event.

    Called async after event ingestion returns 202 to the SDK.
    """
    from app.detection.pipeline import DetectionPipeline

    pipeline = DetectionPipeline()
    results = asyncio.run(pipeline.run(event_data))

    triggered = [r for r in results if r.triggered]

    log.info(
        "detection.completed",
        event_id=event_id,
        total_detectors=len(results),
        triggered_count=len(triggered),
    )

    return {
        "event_id": event_id,
        "results": [
            {
                "detector": r.detector,
                "triggered": r.triggered,
                "severity": r.severity.value,
                "confidence": r.confidence,
                "reason": r.reason,
            }
            for r in results
        ],
        "should_block": pipeline.should_block(results),
    }
