import uuid
from datetime import datetime

from app.schemas.base import ParrySchema


class OrgCreate(ParrySchema):
    name: str
    clerk_org_id: str


class OrgUpdate(ParrySchema):
    name: str | None = None
    is_active: bool | None = None


class OrgResponse(ParrySchema):
    id: uuid.UUID
    name: str
    clerk_org_id: str
    stripe_customer_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
