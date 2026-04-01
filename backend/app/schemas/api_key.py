import uuid
from datetime import datetime

from app.schemas.base import ParrySchema


class ApiKeyCreate(ParrySchema):
    name: str


class ApiKeyResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    key_prefix: str
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the full key (shown once)."""

    raw_key: str
