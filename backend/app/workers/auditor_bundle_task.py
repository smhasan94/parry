"""Celery task: generate auditor bundle ZIP asynchronously.

Long-running for large orgs — writes result to Redis for polling.
"""

import asyncio
from datetime import date

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="generate_auditor_bundle",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def generate_bundle(
    self,
    job_id: str,
    org_id: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict:  # type: ignore[no-untyped-def]
    """Generate bundle and store result in Redis."""
    try:
        return asyncio.run(
            _generate(job_id, org_id, period_start, period_end)
        )
    except Exception:
        _set_job_status(job_id, "failed")
        log.error(
            "auditor_bundle.task_failed",
            job_id=job_id,
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _generate(
    job_id: str,
    org_id: str,
    period_start: str | None,
    period_end: str | None,
) -> dict:
    import uuid

    from app.compliance.auditor_bundle import generate_bundle as build_bundle
    from app.db.session import make_task_session_factory

    _set_job_status(job_id, "running")

    start = date.fromisoformat(period_start) if period_start else None
    end = date.fromisoformat(period_end) if period_end else None

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            zip_bytes = await build_bundle(
                db, uuid.UUID(org_id), period_start=start, period_end=end
            )

        # Store ZIP in Redis with 1h TTL for download
        _store_bundle(job_id, zip_bytes)
        _set_job_status(job_id, "completed")

        log.info(
            "auditor_bundle.completed",
            job_id=job_id,
            org_id=org_id,
            size_bytes=len(zip_bytes),
        )
        return {"job_id": job_id, "status": "completed", "size_bytes": len(zip_bytes)}
    finally:
        await task_engine.dispose()


def _set_job_status(job_id: str, status: str) -> None:
    try:
        from app.core.redis_pool import sync_redis

        r = sync_redis()
        r.setex(f"bundle_job:{job_id}:status", 3600, status)
    except Exception:
        log.debug("auditor_bundle.redis_status_failed", exc_info=True)


def _store_bundle(job_id: str, data: bytes) -> None:
    try:
        from app.core.redis_pool import sync_redis_raw

        r = sync_redis_raw()
        r.setex(f"bundle_job:{job_id}:data", 3600, data)
    except Exception:
        log.warning("auditor_bundle.redis_store_failed", exc_info=True)
