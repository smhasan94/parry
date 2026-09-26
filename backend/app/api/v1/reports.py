"""Compliance report export API.

``GET /api/v1/reports/compliance?start=YYYY-MM-DD&end=YYYY-MM-DD``

Admin+ gated. Generates a PDF synchronously for ranges up to 90 days
and streams the bytes back as ``application/pdf``. Ranges over 90
days (up to the 366-day ceiling) are generated asynchronously via
Celery: this call returns 202 with a job_id, polled at
``GET /compliance/jobs/{job_id}`` and downloaded at
``GET /compliance/jobs/{job_id}/download``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.report_job import ReportJobStatusResponse
from app.services import audit_service, plan_service, report_job_service
from app.services.report_service import build_report_data
from app.services.report_template import render_report_pdf

log = structlog.get_logger()

router = APIRouter()

MAX_SYNC_DAYS = 90
MAX_RANGE_DAYS = 366


@router.get("/compliance")
async def export_compliance_report(
    start: date = Query(..., description="Inclusive start date, YYYY-MM-DD"),
    end: date = Query(..., description="Exclusive end date, YYYY-MM-DD"),
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")

    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )

    span_days = (end - start).days
    if span_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum supported range is {MAX_RANGE_DAYS} days.",
        )

    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end, time.min, tzinfo=UTC)

    if span_days > MAX_SYNC_DAYS:
        return await _dispatch_async_report(db, org, actor, start_dt, end_dt)

    data = await build_report_data(db, org.id, start_dt, end_dt)

    try:
        pdf_bytes = render_report_pdf(data)
    except ImportError as e:  # pragma: no cover - dep missing in dev
        log.error("report.pdf.weasyprint_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation is not available on this server.",
        ) from e
    except OSError as e:
        # WeasyPrint raises OSError when its native deps (Pango,
        # Cairo, libgobject) can't be loaded. Same user-visible
        # story as a missing Python package — the server is
        # misconfigured, not the request.
        log.error("report.pdf.weasyprint_native_deps_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "PDF generation is unavailable: native dependencies "
                "(Pango/Cairo) missing on this backend. See docs/runbook.md."
            ),
        ) from e

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="compliance_report.exported",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="compliance_report",
        resource_id=None,
        details={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bytes": len(pdf_bytes),
            "total_events": data["summary"]["total_events"],
            "total_incidents": data["summary"]["total_incidents"],
        },
    )
    await db.commit()

    log.info(
        "compliance_report.exported",
        org_id=str(org.id),
        start=start.isoformat(),
        end=end.isoformat(),
        bytes=len(pdf_bytes),
    )

    filename = f"parry-compliance-{start.isoformat()}-{end.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


async def _dispatch_async_report(
    db: AsyncSession,
    org: Org,
    actor: Actor,
    start_dt: datetime,
    end_dt: datetime,
) -> Response:
    job_id = str(uuid.uuid4())
    report_job_service.set_report_job_status(job_id, org_id=str(org.id), status="queued")

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="compliance_report.async_requested",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="compliance_report",
        resource_id=None,
        details={
            "job_id": job_id,
            "start": start_dt.date().isoformat(),
            "end": end_dt.date().isoformat(),
        },
    )
    await db.commit()

    try:
        from app.workers.compliance_report_task import generate_compliance_report

        generate_compliance_report.delay(
            job_id, str(org.id), start_dt.isoformat(), end_dt.isoformat()
        )
    except Exception as e:  # pragma: no cover — broker outage
        log.error("compliance_report.enqueue_failed", job_id=job_id, error=str(e))
        # There is no reprocess path for a Redis-only job — mark it
        # failed immediately rather than leaving the caller polling
        # "queued" for a full hour until the TTL silently expires.
        report_job_service.set_report_job_status(job_id, org_id=str(org.id), status="failed")

    import json

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=json.loads(
            ReportJobStatusResponse(job_id=job_id, status="queued").model_dump_json()
        ),
    )


@router.get("/compliance/jobs/{job_id}", response_model=ReportJobStatusResponse)
async def get_compliance_report_job(
    job_id: str,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
) -> ReportJobStatusResponse:
    org, _ = org_actor
    state = report_job_service.get_report_job_status(job_id)
    if state is None or state["org_id"] != str(org.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    download_url = (
        f"/api/v1/reports/compliance/jobs/{job_id}/download"
        if state["status"] == "completed"
        else None
    )
    return ReportJobStatusResponse(job_id=job_id, status=state["status"], download_url=download_url)


@router.get("/compliance/jobs/{job_id}/download")
async def download_compliance_report_job(
    job_id: str,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
) -> Response:
    org, _ = org_actor
    state = report_job_service.get_report_job_status(job_id)
    if state is None or state["org_id"] != str(org.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if state["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is {state['status']}, not ready for download.",
        )

    pdf_bytes = report_job_service.load_report_pdf(job_id)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report expired. Request a new export.",
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="parry-compliance-{job_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )
