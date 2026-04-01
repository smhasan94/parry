import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_org
from app.db.models import IncidentStatus, Org, Severity
from app.db.session import get_db
from app.schemas.incident import IncidentListResponse, IncidentResponse, IncidentUpdate
from app.services import incident_service

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
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    incident = await incident_service.update_incident(
        db,
        org_id=org.id,
        incident_id=incident_id,
        **body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return IncidentResponse.model_validate(incident)
