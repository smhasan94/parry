import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import ParrySchema


class AgentCreate(ParrySchema):
    name: str
    description: str | None = None
    metadata: dict[str, Any] | None = None


class AgentUpdate(ParrySchema):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class AgentResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    baseline: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
