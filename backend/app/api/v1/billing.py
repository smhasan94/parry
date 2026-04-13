"""Billing API — Stripe checkout, portal, and webhook endpoints."""

from typing import Any

import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import async_session_factory, get_db
from app.services import billing_service, plan_service

log = structlog.get_logger()

router = APIRouter()


@router.get("/plan", dependencies=[Depends(require_role(Role.VIEWER))])
async def get_plan(
    org: Org = Depends(get_current_org),
) -> dict[str, Any]:
    """Return the org's current plan and its limit table.

    Consumed by the SettingsPage plan card. Returns raw None for
    unlimited fields so the UI can show "Unlimited" explicitly.
    """
    return {
        "plan": org.plan.value,
        "limits": plan_service.get_limits(org.plan),
    }


@router.post("/checkout", dependencies=[Depends(require_role(Role.OWNER))])
async def create_checkout(
    price_id: str = Query(..., description="Stripe price ID for the plan"),
    success_url: str = Query(...),
    cancel_url: str = Query(...),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a Stripe Checkout session for subscribing to a plan."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured",
        )

    customer_id = await billing_service.ensure_stripe_customer(db, org)
    await db.commit()

    url = billing_service.create_checkout_session(customer_id, price_id, success_url, cancel_url)
    return {"url": url}


@router.post("/portal", dependencies=[Depends(require_role(Role.OWNER))])
async def create_portal(
    return_url: str = Query(...),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a Stripe Billing Portal session for managing subscription."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured",
        )

    customer_id = await billing_service.ensure_stripe_customer(db, org)
    await db.commit()

    url = billing_service.create_portal_session(customer_id, return_url)
    return {"url": url}


@router.post("/webhooks/stripe", status_code=200)
async def stripe_webhook(request: Request) -> dict[str, str]:
    """Receive Stripe webhook events for subscription lifecycle."""
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )

    try:
        event = stripe.Webhook.construct_event(body, sig_header, settings.stripe_webhook_secret)  # type: ignore[no-untyped-call]
    except stripe.SignatureVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
        ) from e

    log.info("billing.webhook_received", event_type=event["type"])

    handled_events = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }

    if event["type"] in handled_events:
        async with async_session_factory() as db:
            await billing_service.handle_subscription_event(db, event["type"], event["data"])
            await db.commit()

    return {"status": "ok"}
