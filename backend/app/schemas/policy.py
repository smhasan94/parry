import uuid
from datetime import datetime
from typing import Any

from app.schemas.base import ParrySchema


class PolicyCreate(ParrySchema):
    name: str
    description: str | None = None
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    max_token_budget: int | None = None
    forbidden_patterns: list[str] | None = None
    custom_rules: dict[str, Any] | None = None


class PolicyUpdate(ParrySchema):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    max_token_budget: int | None = None
    forbidden_patterns: list[str] | None = None
    custom_rules: dict[str, Any] | None = None


class PolicyResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    max_token_budget: int | None = None
    forbidden_patterns: list[str] | None = None
    custom_rules: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
