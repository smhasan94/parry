"""Request/response schemas for the discovery layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SSOIngestRequest(BaseModel):
    """Raw SSO grant records pushed by the customer."""

    events: list[dict[str, Any]] = Field(default_factory=list)


class SSOSyncRequest(BaseModel):
    """Pull directly from an Okta tenant.

    The token is used for this call only and is never persisted or
    returned. Storing it belongs to the probe_credentials flow.
    """

    # This host becomes a server-side request carrying an Authorization
    # header, so it is constrained to real Okta tenants at the edge.
    # app.discovery.okta.resolve_base_url re-checks it — the client must
    # be safe on its own, not only when reached through this route.
    okta_domain: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}\.okta(?:preview|-emea)?\.com$",
        examples=["acme.okta.com"],
    )
    api_token: str = Field(min_length=1, repr=False)


class SSOSyncResponse(BaseModel):
    processed: int
    created: int
    deduplicated: int
    matched: int
    unmatched: int


class ShadowSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider_name: str | None
    risk_level: str
    discovery_source: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None


class ShadowAIResponse(BaseModel):
    total: int
    by_risk_level: dict[str, int]
    systems: list[ShadowSystemResponse]
