import uuid
from datetime import datetime
from typing import Any

from app.db.models import IncidentStatus, Severity
from app.schemas.base import ParrySchema
from app.schemas.detection import DetectionResponse


class IncidentUpdate(ParrySchema):
    status: IncidentStatus | None = None
    title: str | None = None


class IncidentResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    severity: Severity
    status: IncidentStatus
    resolved_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    detections: list[DetectionResponse] = []
    created_at: datetime
    updated_at: datetime


class IncidentListResponse(ParrySchema):
    incidents: list[IncidentResponse]
    next_cursor: str | None = None
    has_more: bool = False
