import uuid
from datetime import datetime
from typing import Any

from app.db.models import Severity
from app.schemas.base import ParrySchema


class DetectionResponse(ParrySchema):
    id: uuid.UUID
    event_id: uuid.UUID
    incident_id: uuid.UUID | None = None
    detector: str
    severity: Severity
    confidence: float
    reason: str
    triggered: bool
    details: dict[str, Any] | None = None
    created_at: datetime


class DetectionResult(ParrySchema):
    """Internal result from running a detector."""

    triggered: bool
    severity: Severity
    confidence: float
    reason: str
    detector: str
    details: dict[str, Any] | None = None
