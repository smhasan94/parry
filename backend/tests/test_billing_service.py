"""Unit tests for billing_service.

The Stripe-side calls and DB-side calls are both mocked — these are
pure-logic tests for ensure_stripe_customer (cache + create branches),
the checkout / portal session pass-throughs, and the subscription
webhook dispatcher (created / updated / deleted / unknown-org).

The pure ``resolve_plan_from_subscription`` price→Plan walk lives in
``test_plan_service.py``; not duplicated here.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Org, Plan
from app.services import billing_service


def _make_org(stripe_customer_id: str | None = None, plan: Plan = Plan.FREE) -> Org:
    return Org(
        id=uuid.uuid4(),
        name="Acme",
        clerk_org_id=f"c_{uuid.uuid4().hex[:8]}",
        is_active=True,
        plan=plan,
        stripe_customer_id=stripe_customer_id,
    )


def _execute_returning(org: Org | None) -> MagicMock:
    """Build the mock chain ``db.execute(...).scalar_one_or_none() -> org``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = org
    return result


# ── ensure_stripe_customer ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_stripe_customer_returns_existing_id_without_calling_stripe() -> None:
    org = _make_org(stripe_customer_id="cus_existing")
    db = AsyncMock()

    with patch.object(billing_service.stripe.Customer, "create") as mock_create:
        result = await billing_service.ensure_stripe_customer(db, org)

    assert result == "cus_existing"
    mock_create.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_stripe_customer_creates_and_persists_when_missing() -> None:
    org = _make_org(stripe_customer_id=None)
    db = AsyncMock()

    fake_customer = MagicMock(id="cus_new_abc")
    with patch.object(
        billing_service.stripe.Customer, "create", return_value=fake_customer
    ) as mock_create:
        result = await billing_service.ensure_stripe_customer(db, org)

    assert result == "cus_new_abc"
    assert org.stripe_customer_id == "cus_new_abc"
    mock_create.assert_called_once()
    # Metadata should carry both the internal org id and the Clerk org id so
    # the Stripe dashboard can be cross-referenced from either side.
    kwargs = mock_create.call_args.kwargs
    assert kwargs["name"] == "Acme"
    assert kwargs["metadata"]["org_id"] == str(org.id)
    assert kwargs["metadata"]["clerk_org_id"] == org.clerk_org_id
    db.flush.assert_awaited_once()


# ── checkout / portal sessions (thin Stripe wrappers) ───────────────


def test_create_checkout_session_returns_session_url() -> None:
    fake_session = MagicMock(url="https://checkout.stripe.com/sess_123")
    with patch.object(
        billing_service.stripe.checkout.Session, "create", return_value=fake_session
    ) as mock_create:
        url = billing_service.create_checkout_session(
            customer_id="cus_1",
            price_id="price_growth",
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )

    assert url == "https://checkout.stripe.com/sess_123"
    kwargs = mock_create.call_args.kwargs
    assert kwargs["customer"] == "cus_1"
    assert kwargs["mode"] == "subscription"
    assert kwargs["line_items"] == [{"price": "price_growth", "quantity": 1}]
    assert kwargs["success_url"] == "https://app/success"
    assert kwargs["cancel_url"] == "https://app/cancel"


def test_create_checkout_session_returns_empty_string_when_url_missing() -> None:
    fake_session = MagicMock(url=None)
    with patch.object(
        billing_service.stripe.checkout.Session, "create", return_value=fake_session
    ):
        url = billing_service.create_checkout_session(
            customer_id="cus_1",
            price_id="price_growth",
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )

    assert url == ""


def test_create_portal_session_returns_portal_url() -> None:
    fake_session = MagicMock(url="https://billing.stripe.com/p/sess_xyz")
    with patch.object(
        billing_service.stripe.billing_portal.Session,
        "create",
        return_value=fake_session,
    ) as mock_create:
        url = billing_service.create_portal_session(
            customer_id="cus_1", return_url="https://app/billing"
        )

    assert url == "https://billing.stripe.com/p/sess_xyz"
    mock_create.assert_called_once_with(
        customer="cus_1", return_url="https://app/billing"
    )


def test_create_portal_session_returns_empty_string_when_url_missing() -> None:
    with patch.object(
        billing_service.stripe.billing_portal.Session,
        "create",
        return_value=MagicMock(url=None),
    ):
        assert (
            billing_service.create_portal_session(
                customer_id="cus_1", return_url="https://app/billing"
            )
            == ""
        )


# ── handle_subscription_event ────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_subscription_deleted_resets_org_to_free() -> None:
    org = _make_org(stripe_customer_id="cus_42", plan=Plan.PRO)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(org)

    payload: dict[str, Any] = {
        "object": {"customer": "cus_42", "status": "canceled"}
    }
    await billing_service.handle_subscription_event(
        db, "customer.subscription.deleted", payload
    )

    assert org.plan == Plan.FREE
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_subscription_updated_promotes_plan_from_price_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_growth", "price_growth_123"
    )
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_pro", "price_pro_456"
    )

    org = _make_org(stripe_customer_id="cus_42", plan=Plan.FREE)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(org)

    payload: dict[str, Any] = {
        "object": {
            "customer": "cus_42",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_pro_456"}}]},
        }
    }
    await billing_service.handle_subscription_event(
        db, "customer.subscription.updated", payload
    )

    assert org.plan == Plan.PRO
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_subscription_created_assigns_growth_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_growth", "price_growth_123"
    )
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_pro", "price_pro_456"
    )

    org = _make_org(stripe_customer_id="cus_42", plan=Plan.FREE)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(org)

    payload: dict[str, Any] = {
        "object": {
            "customer": "cus_42",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_growth_123"}}]},
        }
    }
    await billing_service.handle_subscription_event(
        db, "customer.subscription.created", payload
    )

    assert org.plan == Plan.GROWTH


@pytest.mark.asyncio
async def test_handle_subscription_unknown_price_falls_back_to_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_growth", "price_growth_123"
    )
    monkeypatch.setattr(
        billing_service.settings, "stripe_price_id_pro", "price_pro_456"
    )

    org = _make_org(stripe_customer_id="cus_42", plan=Plan.PRO)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(org)

    payload: dict[str, Any] = {
        "object": {
            "customer": "cus_42",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_unknown"}}]},
        }
    }
    await billing_service.handle_subscription_event(
        db, "customer.subscription.updated", payload
    )

    assert org.plan == Plan.FREE


@pytest.mark.asyncio
async def test_handle_subscription_event_no_op_when_org_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    payload: dict[str, Any] = {
        "object": {"customer": "cus_unknown", "status": "active"}
    }
    await billing_service.handle_subscription_event(
        db, "customer.subscription.updated", payload
    )

    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_handle_subscription_event_ignores_unrelated_event_types() -> None:
    """Non-subscription events shouldn't mutate the org plan."""
    org = _make_org(stripe_customer_id="cus_42", plan=Plan.PRO)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(org)

    payload: dict[str, Any] = {
        "object": {"customer": "cus_42", "status": "active"}
    }
    await billing_service.handle_subscription_event(
        db, "invoice.payment_succeeded", payload
    )

    # Plan untouched; we still call flush because the function always
    # flushes at the bottom — that's fine, the org row is unchanged.
    assert org.plan == Plan.PRO
