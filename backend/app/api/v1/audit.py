"""Audit log API — read-only access to the org's audit trail."""

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_export_service, audit_service

router = APIRouter()


class AuditEntryResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    actor_type: str
    actor_id: str | None = None
    actor_label: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime


class AuditLogResponse(ParrySchema):
    entries: list[AuditEntryResponse]
    next_cursor: str | None = None
    has_more: bool = False


@router.get(
    "",
    response_model=AuditLogResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_audit_log(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(None, description="Filter by action name"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    resource_id: str | None = Query(None, description="Filter by resource ID"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> AuditLogResponse:
    """List audit log entries for the org, newest first."""
    entries, next_cursor = await audit_service.list_audit_log(
        db,
        org.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        cursor=cursor,
        limit=limit,
    )
    return AuditLogResponse(
        entries=[AuditEntryResponse.model_validate(e) for e in entries],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


MAX_EXPORT_DAYS = 400  # SOC 2 audits usually cover a 12-month period.


@router.get("/export")
async def export_audit_log(
    start: date = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end: date = Query(..., description="Exclusive end date (YYYY-MM-DD)"),
    fmt: str = Query("csv", alias="format", pattern="^(csv|json)$"),
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export the audit log for a date range as a tamper-evident CSV or JSON.

    Every row carries ``prev_hash`` + ``row_hash`` columns forming a
    sha256 chain anchored at ``GENESIS``. Auditors can re-walk the
    chain offline to prove the artefact hasn't been edited since it
    left Parry. The export itself is logged to the audit trail with
    the final tip hash, which means any tampering attempt on the
    downloaded file can be detected by comparing against the row
    that records the export.
    """
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )
    if (end - start).days > MAX_EXPORT_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export range exceeds maximum of {MAX_EXPORT_DAYS} days.",
        )

    org, actor = org_actor
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end, time.min, tzinfo=UTC)
    generated_at = datetime.now(UTC)

    body, count, final_hash = await audit_export_service.export_audit_log(
        db,
        org.id,
        start=start_dt,
        end=end_dt,
        fmt=fmt,
        generated_at=generated_at,
    )

    # Self-log the export. Persisting the final chain tip means a
    # future auditor can verify the artefact was produced by Parry
    # without trusting the filename or download metadata.
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="audit_log.exported",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="audit_log_export",
        details={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "format": fmt,
            "entry_count": count,
            "final_row_hash": final_hash,
        },
    )
    await db.commit()

    filename = f"parry-audit-{org.id}-{start.isoformat()}-{end.isoformat()}.{fmt}"
    media_type = "text/csv" if fmt == "csv" else "application/json"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Parry-Chain-Tip": final_hash,
            "X-Parry-Entry-Count": str(count),
        },
    )
