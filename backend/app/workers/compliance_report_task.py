"""Celery task: generate a compliance PDF for a >90-day range.

Long-running for large orgs — writes the finished PDF to Redis for
polling/download, following the same shape as
``app.workers.auditor_bundle_task`` (job_id keyed, 1h TTL) but scoped
by org_id so cross-org download is refused at the route layer.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="generate_compliance_report",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def generate_compliance_report(
    self: Any, job_id: str, org_id: str, start_iso: str, end_iso: str
) -> dict[str, Any]:
    try:
        return asyncio.run(_generate(job_id, org_id, start_iso, end_iso))
    except Exception:
        log.error(
            "compliance_report.task_failed",
            job_id=job_id,
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _generate(
    job_id: str, org_id: str, start_iso: str, end_iso: str
) -> dict[str, Any]:
    from app.db.session import make_task_session_factory
    from app.services.report_job_service import set_report_job_status, store_report_pdf
    from app.services.report_service import build_report_data
    from app.services.report_template import render_report_pdf

    set_report_job_status(job_id, org_id=org_id, status="running")

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            data = await build_report_data(db, uuid.UUID(org_id), start, end)

        pdf_bytes = render_report_pdf(data)
        store_report_pdf(job_id, pdf_bytes)
        set_report_job_status(job_id, org_id=org_id, status="completed")

        log.info(
            "compliance_report.completed",
            job_id=job_id,
            org_id=org_id,
            size_bytes=len(pdf_bytes),
        )
        return {"job_id": job_id, "status": "completed", "size_bytes": len(pdf_bytes)}
    except Exception:
        set_report_job_status(job_id, org_id=org_id, status="failed")
        raise
    finally:
        await task_engine.dispose()
