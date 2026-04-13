"""Stripe billing service — customer management, checkout, and portal."""

from typing import Any

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Org, Plan

log = structlog.get_logger()

stripe.api_key = settings.stripe_secret_key


async def ensure_stripe_customer(db: AsyncSession, org: Org) -> str:
    """Get or create a Stripe customer for the org. Returns customer ID."""
    if org.stripe_customer_id:
        return org.stripe_customer_id

    customer = stripe.Customer.create(
        name=org.name,
        metadata={"org_id": str(org.id), "clerk_org_id": org.clerk_org_id},
    )

    org.stripe_customer_id = customer.id
    await db.flush()

    log.info("billing.customer_created", org_id=str(org.id), customer_id=customer.id)
    return customer.id


def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session. Returns the session URL."""
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url or ""


def create_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Billing Portal session. Returns the portal URL."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url or ""


def _price_to_plan_map() -> dict[str, Plan]:
    """Read the price-id -> plan mapping from settings at call time.

    Evaluating lazily means tests that override settings before calling
    the handler still see the right mapping.
    """
    mapping: dict[str, Plan] = {}
    if settings.stripe_price_id_growth:
        mapping[settings.stripe_price_id_growth] = Plan.GROWTH
    if settings.stripe_price_id_pro:
        mapping[settings.stripe_price_id_pro] = Plan.PRO
    return mapping


def resolve_plan_from_subscription(subscription: dict[str, Any]) -> Plan:
    """Walk the Stripe subscription object to find the matching plan."""
    items = subscription.get("items") or {}
    data = items.get("data") or []
    if not data:
        return Plan.FREE
    price = data[0].get("price") or {}
    price_id = price.get("id") or ""
    return _price_to_plan_map().get(price_id, Plan.FREE)


async def handle_subscription_event(
    db: AsyncSession, event_type: str, data: dict[str, Any],
) -> None:
    """Handle Stripe subscription lifecycle events.

    Sets ``org.plan`` based on the subscription's price id on
    create/update, and resets to FREE on deletion. Never raises — a
    bad webhook payload logs a warning and returns cleanly so Stripe
    doesn't hammer retries for a parsing issue on our side.
    """
    subscription = data.get("object", {})
    customer_id = subscription.get("customer", "")
    status = subscription.get("status", "")

    result = await db.execute(select(Org).where(Org.stripe_customer_id == customer_id))
    org = result.scalar_one_or_none()

    if org is None:
        log.warning("billing.org_not_found", customer_id=customer_id)
        return

    if event_type == "customer.subscription.deleted":
        org.plan = Plan.FREE
        log.info(
            "billing.subscription_canceled",
            org_id=str(org.id),
            plan=org.plan.value,
        )
    elif event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        new_plan = resolve_plan_from_subscription(subscription)
        org.plan = new_plan
        log.info(
            "billing.subscription_updated",
            org_id=str(org.id),
            status=status,
            plan=new_plan.value,
        )

    await db.flush()
