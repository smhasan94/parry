"""Webhook dispatch service — delivers events to customer endpoints.

HMAC-SHA256 signed payloads, async delivery via Celery with exponential
backoff retries. Delivery history recorded for debugging.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_safety import assert_public_https_url_async
from app.db.models import WebhookDelivery, WebhookEndpoint

log = structlog.get_logger()

# Valid event types customers can subscribe to
VALID_EVENT_TYPES = {
    "detection.triggered",
    "incident.created",
    "incident.resolved",
    "permission.denied",
    "threat_intel.match",
    "agent.created",
    "budget.exceeded",
}

# Auto-disable after this many consecutive failures
MAX_FAILURE_COUNT = 10


def generate_secret() -> str:
    """Generate a cryptographically secure webhook secret."""
    return f"whsec_{secrets.token_hex(24)}"


def compute_signature(payload: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload: str, secret: str, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature (constant-time comparison)."""
    expected = compute_signature(payload, secret)
    return hmac.compare_digest(expected, signature)


# ── Dispatch ────────────────────────────────────────────────────


async def dispatch_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Find matching active endpoints for this org and event type,
    enqueue delivery for each. Returns the number of endpoints matched.
    """
    if event_type not in VALID_EVENT_TYPES:
        log.warning("webhook.invalid_event_type", event_type=event_type)
        return 0

    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == org_id,
            WebhookEndpoint.is_active.is_(True),
        )
    )
    endpoints = list(result.scalars().all())

    dispatched = 0
    for endpoint in endpoints:
        # Check if this endpoint subscribes to this event type
        event_types = endpoint.event_types or []
        if event_types and event_type not in event_types:
            continue

        # Skip endpoints that have exceeded failure threshold
        if endpoint.failure_count >= MAX_FAILURE_COUNT:
            continue

        # Enqueue async delivery
        try:
            from app.workers.webhook_delivery_task import deliver_webhook

            deliver_webhook.delay(
                str(endpoint.id),
                event_type,
                json.dumps(payload, default=str),
            )
            dispatched += 1
        except Exception:
            log.debug("webhook.dispatch_enqueue_failed", exc_info=True)

    return dispatched


# ── CRUD ────────────────────────────────────────────────────────


async def list_endpoints(
    db: AsyncSession, org_id: uuid.UUID
) -> list[WebhookEndpoint]:
    result = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.org_id == org_id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    return list(result.scalars().all())


async def get_endpoint(
    db: AsyncSession, org_id: uuid.UUID, endpoint_id: uuid.UUID
) -> WebhookEndpoint | None:
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def create_endpoint(
    db: AsyncSession,
    org_id: uuid.UUID,
    url: str,
    event_types: list[str],
    description: str | None = None,
) -> WebhookEndpoint:
    await assert_public_https_url_async(url)
    endpoint = WebhookEndpoint(
        org_id=org_id,
        url=url,
        secret=generate_secret(),
        description=description,
        event_types=event_types,
    )
    db.add(endpoint)
    await db.flush()
    await db.refresh(endpoint)
    log.info("webhook.endpoint_created", endpoint_id=str(endpoint.id), url=url)
    return endpoint


async def update_endpoint(
    db: AsyncSession,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    **updates: Any,
) -> WebhookEndpoint:
    from app.core.exceptions import NotFoundError

    endpoint = await get_endpoint(db, org_id, endpoint_id)
    if endpoint is None:
        raise NotFoundError("WebhookEndpoint", str(endpoint_id))

    if updates.get("url") is not None:
        await assert_public_https_url_async(updates["url"])

    for key, value in updates.items():
        if value is not None:
            setattr(endpoint, key, value)

    # Reset failure count when re-activated
    if updates.get("is_active") is True:
        endpoint.failure_count = 0

    await db.flush()
    await db.refresh(endpoint)
    return endpoint


async def delete_endpoint(
    db: AsyncSession, org_id: uuid.UUID, endpoint_id: uuid.UUID
) -> bool:
    endpoint = await get_endpoint(db, org_id, endpoint_id)
    if endpoint is None:
        return False
    await db.delete(endpoint)
    await db.flush()
    log.info("webhook.endpoint_deleted", endpoint_id=str(endpoint_id))
    return True


async def list_deliveries(
    db: AsyncSession,
    endpoint_id: uuid.UUID,
    limit: int = 50,
) -> list[WebhookDelivery]:
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.delivered_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
