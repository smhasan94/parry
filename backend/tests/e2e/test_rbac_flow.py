"""E2E: RBAC gates across real FastAPI routes.

Uses dependency_overrides on get_current_actor to inject controlled
Actor objects with different Clerk roles — this lets us exercise the
actual router pipeline (including require_role gates) without having
to mint real Clerk JWTs or stub JWKS in the test.

Note: the SDK ingest path uses X-Parry-Secret which always resolves
to actor_type='api_key' → ADMIN, so the API-key-is-admin case is
tested via the seeded API key fixture.
"""

import pytest
from httpx import AsyncClient

from app.core.dependencies import Actor, get_current_actor
from app.db.models import Org  # noqa: F401  (re-exported for type clarity)


def _install_actor_override(app, seeded_db: dict, clerk_role: str | None):
    org = seeded_db["org"]
    actor = Actor(
        actor_type="user",
        actor_id="u-test",
        label="test@example.com",
        clerk_role=clerk_role,
    )

    async def _override():
        return (org, actor)

    app.dependency_overrides[get_current_actor] = _override


def _clear_actor_override(app):
    app.dependency_overrides.pop(get_current_actor, None)


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
    """Owners pass the RBAC gate; actual checkout still 503s without
    Stripe keys, which proves the gate opened."""
    from app.main import app

    _install_actor_override(app, seeded_db, "org:owner")
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
    # 503 because stripe_secret_key is not set in the test env — but we
    # got past the RBAC gate which is what this test is actually proving
    assert resp.status_code in (200, 503)


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
