"""Scheduled security report service.

CRUD for report schedules + next_send_at computation. The actual
generation and delivery is handled by the Celery task.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScheduledReport

log = structlog.get_logger()


def compute_next_send(schedule: str, from_dt: datetime | None = None) -> datetime:
    """Compute the next send time for a schedule.

    weekly: next Monday at 08:00 UTC
    monthly: 1st of next month at 08:00 UTC
    """
    now = from_dt or datetime.now(UTC)

    if schedule == "weekly":
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 8:
            days_until_monday = 7
        next_dt = now.replace(hour=8, minute=0, second=0, microsecond=0)
        next_dt += timedelta(days=days_until_monday)
        return next_dt

    # monthly
    if now.month == 12:
        next_dt = now.replace(
            year=now.year + 1, month=1, day=1, hour=8, minute=0, second=0, microsecond=0
        )
    else:
        next_dt = now.replace(month=now.month + 1, day=1, hour=8, minute=0, second=0, microsecond=0)
    return next_dt


async def list_schedules(
    db: AsyncSession, org_id: uuid.UUID
) -> list[ScheduledReport]:
    result = await db.execute(
        select(ScheduledReport)
        .where(ScheduledReport.org_id == org_id)
        .order_by(ScheduledReport.created_at.desc())
    )
    return list(result.scalars().all())


async def get_schedule(
    db: AsyncSession, org_id: uuid.UUID, schedule_id: uuid.UUID
) -> ScheduledReport | None:
    result = await db.execute(
        select(ScheduledReport).where(
            ScheduledReport.id == schedule_id,
            ScheduledReport.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def create_schedule(
    db: AsyncSession,
    org_id: uuid.UUID,
    schedule: str,
    recipients: list[str],
    report_type: str = "security_summary",
) -> ScheduledReport:
    report = ScheduledReport(
        org_id=org_id,
        schedule=schedule,
        recipients=recipients,
        report_type=report_type,
        next_send_at=compute_next_send(schedule),
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)
    log.info(
        "scheduled_report.created",
        report_id=str(report.id),
        schedule=schedule,
        recipients_count=len(recipients),
    )
    return report


async def update_schedule(
    db: AsyncSession,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
    **updates: Any,
) -> ScheduledReport:
    from app.core.exceptions import NotFoundError

    report = await get_schedule(db, org_id, schedule_id)
    if report is None:
        raise NotFoundError("ScheduledReport", str(schedule_id))

    for key, value in updates.items():
        if value is not None:
            setattr(report, key, value)

    # Recompute next_send if schedule changed
    if "schedule" in updates and updates["schedule"] is not None:
        report.next_send_at = compute_next_send(report.schedule)

    # Reset failure state when re-activated
    if updates.get("is_active") is True:
        report.next_send_at = compute_next_send(report.schedule)

    await db.flush()
    await db.refresh(report)
    return report


async def delete_schedule(
    db: AsyncSession, org_id: uuid.UUID, schedule_id: uuid.UUID
) -> bool:
    report = await get_schedule(db, org_id, schedule_id)
    if report is None:
        return False
    await db.delete(report)
    await db.flush()
    return True


async def get_due_schedules(db: AsyncSession) -> list[ScheduledReport]:
    """Return all active schedules past their next_send_at."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(ScheduledReport).where(
            ScheduledReport.is_active.is_(True),
            ScheduledReport.next_send_at <= now,
        )
    )
    return list(result.scalars().all())
