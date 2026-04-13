"""Clerk webhook handler — syncs org lifecycle events to Parry database."""

from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.core.config import settings
from app.db.models import Org
from app.db.session import async_session_factory

log = structlog.get_logger()

router = APIRouter()


def _verify_webhook(payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Verify Clerk webhook signature using Svix and return parsed event."""
    if not settings.clerk_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured",
        )

    wh = Webhook(settings.clerk_webhook_secret)
    try:
        return wh.verify(payload, headers)  # type: ignore[no-any-return]
    except WebhookVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        ) from e


@router.post("/clerk", status_code=200)
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None),
    svix_timestamp: str = Header(None),
    svix_signature: str = Header(None),
) -> dict[str, str]:
    """Receive Clerk webhook events for org lifecycle management."""
    body = await request.body()

    headers = {
        "svix-id": svix_id or "",
        "svix-timestamp": svix_timestamp or "",
        "svix-signature": svix_signature or "",
    }

    event = _verify_webhook(body, headers)
    event_type = event.get("type", "")

    log.info("webhook.clerk.received", event_type=event_type)

    async with async_session_factory() as db:
        if event_type == "organization.created":
            await _handle_org_created(db, event["data"])
        elif event_type == "organization.updated":
            await _handle_org_updated(db, event["data"])
        elif event_type == "organization.deleted":
            await _handle_org_deleted(db, event["data"])
        elif event_type == "user.created":
            await _handle_user_created(db, event["data"])
        else:
            log.debug("webhook.clerk.ignored", event_type=event_type)

        await db.commit()

    return {"status": "ok"}


async def _handle_org_created(db: AsyncSession, data: dict[str, Any]) -> None:
    """Create a new Org when a Clerk organization is created."""
    clerk_org_id = data.get("id", "")
    name = data.get("name", "Unnamed Organization")

    # Check if org already exists (idempotency)
    result = await db.execute(select(Org).where(Org.clerk_org_id == clerk_org_id))
    if result.scalar_one_or_none():
        log.info("webhook.org_created.already_exists", clerk_org_id=clerk_org_id)
        return

    org = Org(name=name, clerk_org_id=clerk_org_id, is_active=True)
    db.add(org)
    await db.flush()

    log.info("webhook.org_created", org_id=str(org.id), clerk_org_id=clerk_org_id, name=name)


async def _handle_org_updated(db: AsyncSession, data: dict[str, Any]) -> None:
    """Update Org name when a Clerk organization is updated."""
    clerk_org_id = data.get("id", "")
    name = data.get("name")

    result = await db.execute(select(Org).where(Org.clerk_org_id == clerk_org_id))
    org = result.scalar_one_or_none()

    if org is None:
        log.warning("webhook.org_updated.not_found", clerk_org_id=clerk_org_id)
        return

    if name:
        org.name = name
    await db.flush()

    log.info("webhook.org_updated", org_id=str(org.id), name=name)


async def _handle_org_deleted(db: AsyncSession, data: dict[str, Any]) -> None:
    """Deactivate Org when a Clerk organization is deleted."""
    clerk_org_id = data.get("id", "")

    result = await db.execute(select(Org).where(Org.clerk_org_id == clerk_org_id))
    org = result.scalar_one_or_none()

    if org is None:
        log.warning("webhook.org_deleted.not_found", clerk_org_id=clerk_org_id)
        return

    org.is_active = False
    await db.flush()

    log.info("webhook.org_deleted", org_id=str(org.id), clerk_org_id=clerk_org_id)


async def _handle_user_created(db: AsyncSession, data: dict[str, Any]) -> None:
    """Create a personal Org when a new user signs up without an organization."""
    user_id = data.get("id", "")
    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    name = f"{first_name} {last_name}".strip() or "Personal"

    # Use user_id as clerk_org_id for personal orgs
    result = await db.execute(select(Org).where(Org.clerk_org_id == user_id))
    if result.scalar_one_or_none():
        log.info("webhook.user_created.org_exists", user_id=user_id)
        return

    org = Org(name=f"{name}'s Workspace", clerk_org_id=user_id, is_active=True)
    db.add(org)
    await db.flush()

    log.info("webhook.user_created.org_created", org_id=str(org.id), user_id=user_id)
