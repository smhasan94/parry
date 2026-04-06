import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import IncidentStatus, Org, Severity
from app.db.session import get_db
from app.schemas.incident import IncidentListResponse, IncidentResponse, IncidentUpdate
from app.services import audit_service, incident_service

router = APIRouter()


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    severity: Severity | None = Query(None),
    status: IncidentStatus | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> IncidentListResponse:
    incidents, next_cursor = await incident_service.list_incidents(
        db, org.id, severity=severity, status=status, cursor=cursor, limit=limit
    )
    return IncidentListResponse(
        incidents=[IncidentResponse.model_validate(i) for i in incidents],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    incident = await incident_service.get_incident(db, org.id, incident_id)
    return IncidentResponse.model_validate(incident)


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    org, actor = org_actor

    # Capture the previous status for the audit diff
    previous = await incident_service.get_incident(db, org.id, incident_id)
    previous_status = previous.status.value

    incident = await incident_service.update_incident(
        db,
        org_id=org.id,
        incident_id=incident_id,
        **body.model_dump(exclude_unset=True),
    )

    # Audit log the change
    if body.status is not None and body.status.value != previous_status:
        await audit_service.log_action(
            db,
            org_id=org.id,
            action=f"incident.{body.status.value}",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_label=actor.label,
            resource_type="incident",
            resource_id=str(incident_id),
            details={
                "previous_status": previous_status,
                "new_status": body.status.value,
                "title": incident.title,
                "severity": incident.severity.value,
            },
        )

    await db.commit()
    return IncidentResponse.model_validate(incident)
