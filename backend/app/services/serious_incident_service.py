"""Article 73 serious incident reporting service.

Creates draft reports from CRITICAL Parry incidents, tracks the 15-day
reporting deadline, and handles finalization with PDF rendering.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Incident, SeriousIncident

log = structlog.get_logger()


async def create_draft(
    db: AsyncSession,
    org_id: uuid.UUID,
    incident_id: uuid.UUID,
    system_id: uuid.UUID | None = None,
    created_by: str | None = None,
) -> SeriousIncident:
    """Create a serious incident report draft from a Parry incident."""
    # Load the incident
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.org_id == org_id
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise NotFoundError("Incident", str(incident_id))

    # Check if a report already exists for this incident
    existing = await db.execute(
        select(SeriousIncident).where(
            SeriousIncident.incident_id == incident_id
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(
            f"A serious incident report already exists for incident {incident_id}"
        )

    # 15-day deadline from incident creation
    deadline = incident.created_at + timedelta(days=15)

    # Pre-fill the report content from incident data
    report_content = _build_report_content(incident)

    report = SeriousIncident(
        org_id=org_id,
        incident_id=incident_id,
        system_id=system_id,
        deadline_at=deadline,
        report_content=report_content,
        created_by=created_by,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)

    log.info(
        "serious_incident.created",
        report_id=str(report.id),
        incident_id=str(incident_id),
        deadline=deadline.isoformat(),
    )
    return report


async def get_report(
    db: AsyncSession, org_id: uuid.UUID, report_id: uuid.UUID
) -> SeriousIncident:
    result = await db.execute(
        select(SeriousIncident).where(
            SeriousIncident.id == report_id, SeriousIncident.org_id == org_id
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise NotFoundError("SeriousIncident", str(report_id))
    return report


async def list_reports(
    db: AsyncSession,
    org_id: uuid.UUID,
    unreported_only: bool = False,
) -> list[SeriousIncident]:
    query = (
        select(SeriousIncident)
        .where(SeriousIncident.org_id == org_id)
        .order_by(SeriousIncident.created_at.desc())
    )
    if unreported_only:
        query = query.where(SeriousIncident.reported_to_authority_at.is_(None))
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_draft(
    db: AsyncSession,
    org_id: uuid.UUID,
    report_id: uuid.UUID,
    report_content: dict | None = None,
    authority_jurisdiction: str | None = None,
    system_id: uuid.UUID | None = None,
) -> SeriousIncident:
    """Update a draft report with user-provided fields."""
    report = await get_report(db, org_id, report_id)
    if report.reported_to_authority_at is not None:
        raise ConflictError("Cannot edit a finalized report")

    if report_content is not None:
        # Merge with existing content
        merged = {**report.report_content, **report_content}
        report.report_content = merged
    if authority_jurisdiction is not None:
        report.authority_jurisdiction = authority_jurisdiction
    if system_id is not None:
        report.system_id = system_id

    await db.flush()
    await db.refresh(report)
    log.info("serious_incident.updated", report_id=str(report_id))
    return report


async def finalize(
    db: AsyncSession,
    org_id: uuid.UUID,
    report_id: uuid.UUID,
    finalized_by: str,
) -> SeriousIncident:
    """Mark report as submitted to authority, render PDF."""
    report = await get_report(db, org_id, report_id)
    if report.reported_to_authority_at is not None:
        raise ConflictError("Report already finalized")

    report.reported_to_authority_at = datetime.now(UTC)

    # Render PDF
    try:
        from app.compliance.incident_report_template import render_incident_pdf

        report.pdf_bytes = render_incident_pdf(report)
    except Exception:
        log.warning(
            "serious_incident.pdf_failed",
            report_id=str(report_id),
            exc_info=True,
        )

    await db.flush()
    await db.refresh(report)
    log.info(
        "serious_incident.finalized",
        report_id=str(report_id),
        finalized_by=finalized_by,
    )
    return report


def _build_report_content(incident: Incident) -> dict:
    """Pre-fill report template from incident data."""
    return {
        "incident_summary": {
            "title": incident.title,
            "severity": incident.severity.value if incident.severity else None,
            "status": incident.status.value if incident.status else None,
            "detected_at": incident.created_at.isoformat() if incident.created_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        "description_of_incident": None,
        "affected_persons": None,
        "measures_taken": None,
        "root_cause_analysis": None,
        "corrective_actions": None,
        "contact_information": {
            "reporting_officer_name": None,
            "reporting_officer_title": None,
            "reporting_officer_email": None,
            "reporting_officer_phone": None,
        },
        "authority_information": {
            "authority_name": None,
            "authority_jurisdiction": None,
            "reference_number": None,
        },
    }


def days_remaining(report: SeriousIncident) -> int:
    """Days until the 15-day reporting deadline. Negative if overdue."""
    if report.reported_to_authority_at:
        return 0
    delta = report.deadline_at - datetime.now(UTC)
    return delta.days
