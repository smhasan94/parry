"""Celery tasks for threat intelligence.

Two tasks:
1. extract_threat_pattern — async extraction after high-confidence detection
2. threat_intel_decay — daily decay + archival of stale indicators
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


# ── Pattern extraction task ────────────────────────────────────


@celery_app.task(  # type: ignore[untyped-decorator]
    name="extract_threat_pattern",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
    soft_time_limit=15,
    time_limit=30,
)
def extract_threat_pattern(
    self: Any,
    org_id: str,
    detection_id: str,
    detector: str,
    severity: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    """Extract and record a threat pattern from a detection."""
    try:
        return asyncio.run(
            _extract(org_id, detection_id, detector, severity, confidence, reason)
        )
    except Exception:
        log.error(
            "threat_intel.extraction_failed",
            detection_id=detection_id,
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _extract(
    org_id: str,
    detection_id: str,
    detector: str,
    severity: str,
    confidence: float,
    reason: str,
) -> dict[str, Any]:
    import uuid

    from app.db.session import make_task_session_factory
    from app.services.threat_intel_service import extract_and_record

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            indicator = await extract_and_record(
                db,
                org_id=uuid.UUID(org_id),
                detection_id=uuid.UUID(detection_id),
                detector=detector,
                severity=severity,
                confidence=confidence,
                reason=reason,
            )
            await db.commit()

        if indicator:
            return {
                "pattern_hash": indicator.pattern_hash,
                "org_count": indicator.org_count,
                "promoted": indicator.promoted_at is not None,
            }
        return {"skipped": True}
    finally:
        await task_engine.dispose()


# ── Daily decay task ───────────────────────────────────────────


@celery_app.task(  # type: ignore[untyped-decorator]
    name="threat_intel_decay",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=120,
    time_limit=300,
)
def threat_intel_decay(self: Any) -> dict[str, Any]:
    """Daily: decay scores, promote eligible, archive stale indicators."""
    try:
        return asyncio.run(_decay_all())
    except Exception:
        log.error(
            "threat_intel.decay_failed",
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _decay_all() -> dict[str, Any]:
    from sqlalchemy import update

    from app.db.models import ThreatIndicator
    from app.db.session import make_task_session_factory
    from app.services.threat_intel_service import (
        ARCHIVE_SCORE_THRESHOLD,
        ARCHIVE_STALE_DAYS,
        DECAY_FACTOR,
        PROMOTION_THRESHOLD,
    )

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=ARCHIVE_STALE_DAYS)

    try:
        async with factory() as db:
            # 1. Decay all non-archived scores
            await db.execute(
                update(ThreatIndicator)
                .where(ThreatIndicator.archived_at.is_(None))
                .values(score=ThreatIndicator.score * DECAY_FACTOR)
            )

            # 2. Promote indicators that crossed the threshold
            from sqlalchemy import select

            unpromoted = await db.execute(
                select(ThreatIndicator).where(
                    ThreatIndicator.promoted_at.is_(None),
                    ThreatIndicator.archived_at.is_(None),
                    ThreatIndicator.org_count >= PROMOTION_THRESHOLD,
                )
            )
            promoted_count = 0
            for ind in unpromoted.scalars().all():
                ind.promoted_at = now
                promoted_count += 1

            # 3. Archive stale indicators
            archived_result = await db.execute(
                update(ThreatIndicator)
                .where(
                    ThreatIndicator.archived_at.is_(None),
                    ThreatIndicator.score < ARCHIVE_SCORE_THRESHOLD,
                    ThreatIndicator.last_seen_at < stale_cutoff,
                )
                .values(archived_at=now)
            )
            archived_count = archived_result.rowcount  # type: ignore[attr-defined]

            await db.commit()

        log.info(
            "threat_intel.decay_completed",
            promoted=promoted_count,
            archived=archived_count,
        )
        return {
            "promoted": promoted_count,
            "archived": archived_count,
        }
    finally:
        await task_engine.dispose()
