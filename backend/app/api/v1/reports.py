"""Compliance report export API.

``GET /api/v1/reports/compliance?start=YYYY-MM-DD&end=YYYY-MM-DD``

Admin+ gated. Generates a PDF synchronously for ranges up to 90 days
and streams the bytes back as ``application/pdf``. Longer ranges are
rejected; the async/Celery path is TODO for a future plan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.services import audit_service, plan_service
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
    if span_days > MAX_SYNC_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Ranges over {MAX_SYNC_DAYS} days require async generation, "
                "which is not yet available. Narrow the window and retry."
            ),
        )

    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end, time.min, tzinfo=UTC)

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
