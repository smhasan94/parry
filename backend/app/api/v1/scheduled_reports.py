"""Scheduled security report CRUD routes."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, plan_service, scheduled_report_service

log = structlog.get_logger()
router = APIRouter()


class ScheduleCreateRequest(ParrySchema):
    schedule: str  # weekly | monthly
    recipients: list[str]
    report_type: str = "security_summary"


class ScheduleUpdateRequest(ParrySchema):
    schedule: str | None = None
    recipients: list[str] | None = None
    report_type: str | None = None
    is_active: bool | None = None


class ScheduleResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    schedule: str
    recipients: list[str]
    report_type: str
    is_active: bool
    last_sent_at: datetime | None
    next_send_at: datetime
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduleResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "compliance_export")
    schedules = await scheduled_report_service.list_schedules(db, org.id)
    return [ScheduleResponse.model_validate(s) for s in schedules]


@router.post("", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    body: ScheduleCreateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")

    if body.schedule not in ("weekly", "monthly"):
        raise HTTPException(status_code=400, detail="Schedule must be weekly or monthly")
    if not body.recipients:
        raise HTTPException(status_code=400, detail="At least one recipient required")

    schedule = await scheduled_report_service.create_schedule(
        db, org.id, schedule=body.schedule, recipients=body.recipients,
        report_type=body.report_type,
    )
    await audit_service.log_action(
        db, org_id=org.id, action="scheduled_report.created",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="scheduled_report",
        resource_id=str(schedule.id),
        details={"schedule": body.schedule, "recipients_count": len(body.recipients)},
    )
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")
    schedule = await scheduled_report_service.update_schedule(
        db, org.id, schedule_id, **body.model_dump(exclude_unset=True),
    )
    await audit_service.log_action(
        db, org_id=org.id, action="scheduled_report.updated",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="scheduled_report",
        resource_id=str(schedule_id),
    )
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")
    deleted = await scheduled_report_service.delete_schedule(db, org.id, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await audit_service.log_action(
        db, org_id=org.id, action="scheduled_report.deleted",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="scheduled_report",
        resource_id=str(schedule_id),
    )
    await db.commit()
