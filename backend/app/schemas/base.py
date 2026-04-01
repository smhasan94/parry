import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ParrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CursorPage(ParrySchema):
    """Cursor-based pagination metadata."""

    next_cursor: str | None = None
    has_more: bool = False


class IDTimestamp(ParrySchema):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
