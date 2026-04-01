import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import ParrySchema


class EventIngest(ParrySchema):
    """Payload sent by the SDK."""

    agent_id: str
    session_id: str | None = None
    prompt: str | None = None
    response: str | None = None
    model: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    latency_ms: int | None = None
    token_count: int | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None


class EventResponse(ParrySchema):
    id: uuid.UUID
    agent_id: uuid.UUID
    session_id: uuid.UUID | None = None
    timestamp: datetime
    prompt: str | None = None
    response: str | None = None
    model: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    latency_ms: int | None = None
    token_count: int | None = None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")


class EventListResponse(ParrySchema):
    events: list[EventResponse]
    next_cursor: str | None = None
    has_more: bool = False
