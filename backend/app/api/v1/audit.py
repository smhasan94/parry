"""Audit log API — read-only access to the org's audit trail."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service

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
