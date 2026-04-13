import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Incident, IncidentStatus, Severity

log = structlog.get_logger()


async def list_incidents(
    db: AsyncSession,
    org_id: uuid.UUID,
    severity: Severity | None = None,
    status: IncidentStatus | None = None,
    session_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Incident], str | None]:
    query = select(Incident).where(Incident.org_id == org_id).order_by(Incident.created_at.desc())

    if severity:
        query = query.where(Incident.severity == severity)
    if status:
        query = query.where(Incident.status == status)
    if session_id:
        query = query.where(Incident.metadata_["trigger_session_id"].as_string() == session_id)
    if cursor:
        cursor_id = uuid.UUID(cursor)
        cursor_incident = await db.get(Incident, cursor_id)
        if cursor_incident:
            query = query.where(Incident.created_at < cursor_incident.created_at)

    query = query.limit(limit + 1)
    result = await db.execute(query)
    incidents = list(result.scalars().all())

    next_cursor = None
    if len(incidents) > limit:
        incidents = incidents[:limit]
        next_cursor = str(incidents[-1].id)

    return incidents, next_cursor


async def get_incident(db: AsyncSession, org_id: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    result = await db.execute(
        select(Incident).where(Incident.id == incident_id, Incident.org_id == org_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise NotFoundError("Incident", str(incident_id))
    return incident


async def update_incident(
    db: AsyncSession,
    org_id: uuid.UUID,
    incident_id: uuid.UUID,
    status: IncidentStatus | None = None,
    title: str | None = None,
) -> Incident:
    incident = await get_incident(db, org_id, incident_id)

    if status is not None:
        incident.status = status
    if title is not None:
        incident.title = title

    await db.flush()
    await db.refresh(incident)
    log.info("incident.updated", incident_id=str(incident_id), status=status)
    return incident
