"""Daily compliance refresh task — 03:00 UTC.

Recomputes posture for every org, checks for stale FRIAs (>12 months),
and alerts on overdue CRITICAL incidents past the 15-day deadline.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from app.workers.celery_app import celery_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


@celery_app.task(
    name="compliance_refresh",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def compliance_refresh(self) -> dict:  # type: ignore[no-untyped-def]
    """Daily compliance posture refresh for all orgs."""
    try:
        return asyncio.run(_refresh_all())
    except Exception:
        log.error(
            "compliance_refresh.failed",
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _refresh_all() -> dict:
    from sqlalchemy import select

    from app.db.models import Org
    from app.db.session import make_task_session_factory

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    orgs_processed = 0
    stale_frias = 0
    overdue_incidents = 0

    try:
        async with factory() as db:
            result = await db.execute(select(Org).where(Org.is_active.is_(True)))
            orgs = list(result.scalars().all())

            for org in orgs:
                stats = await _refresh_org(db, org.id)
                stale_frias += stats["stale_frias"]
                overdue_incidents += stats["overdue_incidents"]
                orgs_processed += 1

            await db.commit()

        log.info(
            "compliance_refresh.completed",
            orgs_processed=orgs_processed,
            stale_frias=stale_frias,
            overdue_incidents=overdue_incidents,
        )
        return {
            "orgs_processed": orgs_processed,
            "stale_frias": stale_frias,
            "overdue_incidents": overdue_incidents,
        }
    finally:
        await task_engine.dispose()


async def _refresh_org(db: AsyncSession, org_id) -> dict:  # type: ignore[no-untyped-def]

    from sqlalchemy import select

    from app.db.models import (
        AISystem,
        FRIADocument,
        Incident,
        SeriousIncident,
        Severity,
    )
    from app.services import audit_service
    from app.services.compliance_posture_service import _cache_posture, compute_posture

    stats = {"stale_frias": 0, "overdue_incidents": 0}

    # 1. Recompute and cache posture
    obligations = await compute_posture(db, org_id)
    _cache_posture(org_id, obligations)

    # 2. Check FRIAs > 12 months → mark stale
    cutoff = date.today() - timedelta(days=365)
    fria_result = await db.execute(
        select(FRIADocument).where(
            FRIADocument.org_id == org_id,
            FRIADocument.status == "approved",
            FRIADocument.next_review_date <= cutoff,
        )
    )
    for doc in fria_result.scalars().all():
        doc.status = "stale"
        stats["stale_frias"] += 1
        # Update parent system
        system_result = await db.execute(
            select(AISystem).where(AISystem.id == doc.system_id)
        )
        system = system_result.scalar_one_or_none()
        if system:
            system.fria_status = "stale"

        log.warning(
            "compliance_refresh.fria_stale",
            fria_id=str(doc.id),
            org_id=str(org_id),
            next_review_date=str(doc.next_review_date),
        )

    # 3. Check unresolved CRITICAL incidents past 15-day deadline
    fifteen_days_ago = datetime.now(UTC) - timedelta(days=15)
    critical_result = await db.execute(
        select(Incident).where(
            Incident.org_id == org_id,
            Incident.severity == Severity.CRITICAL,
            Incident.created_at < fifteen_days_ago,
        )
    )
    for inc in critical_result.scalars().all():
        # Check if a finalized report exists
        report_result = await db.execute(
            select(SeriousIncident).where(
                SeriousIncident.incident_id == inc.id,
                SeriousIncident.reported_to_authority_at.is_not(None),
            )
        )
        if report_result.scalar_one_or_none() is None:
            stats["overdue_incidents"] += 1
            log.warning(
                "compliance_refresh.incident_overdue",
                incident_id=str(inc.id),
                org_id=str(org_id),
                created_at=inc.created_at.isoformat(),
            )

    # 4. Log the check
    await audit_service.log_action(
        db,
        org_id=org_id,
        action="compliance.daily_refresh",
        details={
            "stale_frias": stats["stale_frias"],
            "overdue_incidents": stats["overdue_incidents"],
        },
    )

    await db.flush()
    return stats
