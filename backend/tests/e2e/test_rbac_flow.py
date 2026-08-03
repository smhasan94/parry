"""E2E: RBAC gates across real FastAPI routes.

Uses dependency_overrides on get_current_actor to inject controlled
Actor objects with different Clerk roles — this lets us exercise the
actual router pipeline (including require_role gates) without having
to mint real Clerk JWTs or stub JWKS in the test.

Note: the SDK ingest path uses X-Parry-Secret which always resolves
to actor_type='api_key' → ADMIN, so the API-key-is-admin case is
tested via the seeded API key fixture.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import Org  # noqa: F401  (re-exported for type clarity)


def _install_actor_override(app, seeded_db: dict, clerk_role: str | None):
    org = seeded_db["org"]
    actor = Actor(
        actor_type="user",
        actor_id="u-test",
        label="test@example.com",
        clerk_role=clerk_role,
    )

    async def _actor_override():
        return (org, actor)

    async def _org_override():
        return org

    # Both deps need overriding: require_role uses get_current_actor,
    # but routes also Depends(get_current_org) directly which would
    # otherwise try to resolve the dummy Bearer JWT against Clerk
    # and 500 on "invalid JWT" before the role check ever runs.
    app.dependency_overrides[get_current_actor] = _actor_override
    app.dependency_overrides[get_current_org] = _org_override


def _clear_actor_override(app):
    app.dependency_overrides.pop(get_current_actor, None)
    app.dependency_overrides.pop(get_current_org, None)


@pytest.mark.asyncio
async def test_viewer_cannot_create_agent(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor_override(app, seeded_db, "org:viewer")
    try:
        resp = await client.post(
            "/api/v1/agents",
            json={"name": "nope", "description": "viewer tried"},
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear_actor_override(app)
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_viewer_can_list_agents(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor_override(app, seeded_db, "org:viewer")
    try:
        resp = await client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear_actor_override(app)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_create_agent(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor_override(app, seeded_db, "org:admin")
    try:
        resp = await client.post(
            "/api/v1/agents",
            json={"name": "admin-agent", "description": "ok"},
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear_actor_override(app)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_admin_cannot_access_billing_checkout(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor_override(app, seeded_db, "org:admin")
    try:
        resp = await client.post(
            "/api/v1/billing/checkout",
            params={
                "price_id": "price_test",
                "success_url": "https://ok",
                "cancel_url": "https://cancel",
            },
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear_actor_override(app)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_reach_billing_checkout(client: AsyncClient, seeded_db: dict):
    """Owners pass the RBAC gate on checkout.

    Stripe is stubbed out entirely. This test is about the gate, and it
    previously accepted ``in (200, 503)`` — which passes both when the
    gate opens and when billing is simply unconfigured, so it proved
    nothing on its own. Worse, it read stripe_secret_key from the ambient
    environment: with a key present the route called the live Stripe API
    and failed on the credentials rather than on anything about RBAC.
    """
    from app.api.v1 import billing
    from app.main import app

    _install_actor_override(app, seeded_db, "org:owner")
    try:
        with (
            patch.object(billing.settings, "stripe_secret_key", "sk_test_stub"),
            patch.object(
                billing.billing_service,
                "ensure_stripe_customer",
                new=AsyncMock(return_value="cus_stub"),
            ),
            patch.object(
                billing.billing_service,
                "create_checkout_session",
                return_value="https://checkout.stripe.test/session",
            ) as create_session,
        ):
            resp = await client.post(
                "/api/v1/billing/checkout",
                params={
                    "price_id": "price_test",
                    "success_url": "https://ok",
                    "cancel_url": "https://cancel",
                },
                headers={"Authorization": "Bearer dummy-jwt"},
            )
    finally:
        _clear_actor_override(app)

    assert resp.status_code == 200
    assert resp.json()["url"] == "https://checkout.stripe.test/session"
    # The gate opened *and* the handler ran with the caller's arguments.
    assert create_session.call_args.args[1] == "price_test"


@pytest.mark.asyncio
async def test_checkout_reports_unconfigured_billing_rather_than_failing_open(
    client: AsyncClient, seeded_db: dict
):
    """With no Stripe key, an owner gets 503 — not a crash, and not a
    silent success."""
    from app.api.v1 import billing
    from app.main import app

    _install_actor_override(app, seeded_db, "org:owner")
    try:
        with patch.object(billing.settings, "stripe_secret_key", ""):
            resp = await client.post(
                "/api/v1/billing/checkout",
                params={
                    "price_id": "price_test",
                    "success_url": "https://ok",
                    "cancel_url": "https://cancel",
                },
                headers={"Authorization": "Bearer dummy-jwt"},
            )
    finally:
        _clear_actor_override(app)

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_api_key_treated_as_admin_for_ingest(client: AsyncClient, seeded_db: dict):
    """SDK path via X-Parry-Secret never touches the RBAC gate (it uses
    its own dependency chain that bypasses get_current_actor), but we
    verify the happy path here to lock in that the plan's 'api keys
    are always admin' promise holds end-to-end."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "hi",
            "response": "hi back",
            "model": "gpt-4o",
            "latency_ms": 100,
            "token_count": 10,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
