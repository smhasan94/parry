"""RBAC and wiring for the classification review endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import AISystem, RiskClassification


def _install_actor(app, org, clerk_role: str | None, actor_id: str = "u-review"):
    actor = Actor(actor_type="user", actor_id=actor_id, label="ada@corp.com", clerk_role=clerk_role)

    async def _actor_override():
        return (org, actor)

    async def _org_override():
        return org

    app.dependency_overrides[get_current_actor] = _actor_override
    app.dependency_overrides[get_current_org] = _org_override


def _clear(app):
    app.dependency_overrides.pop(get_current_actor, None)
    app.dependency_overrides.pop(get_current_org, None)


async def _pending(db: AsyncSession, org, *, tier: str = "high") -> RiskClassification:
    system = AISystem(
        org_id=org.id,
        name="HireVue",
        origin="discovered",
        discovery_source="sso",
        risk_level="unclassified",
        status="active",
        agent_ids=[],
        last_seen_at=datetime.now(UTC),
    )
    db.add(system)
    await db.flush()
    rc = RiskClassification(
        org_id=org.id,
        system_id=system.id,
        source="catalog",
        risk_tier=tier,
        reasoning="Annex III employment screening.",
        status="pending_review",
    )
    db.add(rc)
    await db.flush()
    await db.commit()
    return rc


@pytest.mark.asyncio
async def test_viewer_can_read_the_review_queue(client: AsyncClient, seeded_db: dict):
    from app.main import app

    org = seeded_db["org"]
    _install_actor(app, org, "org:viewer")
    try:
        resp = await client.get(
            "/api/v1/compliance/classifications",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_viewer_cannot_approve(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    from app.main import app

    org = seeded_db["org"]
    rc = await _pending(db, org)
    _install_actor(app, org, "org:viewer")
    try:
        resp = await client.post(
            f"/api/v1/compliance/classifications/{rc.id}/approve",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    # Setting an Annex III tier of record is not a read-only action.
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_approve_and_the_tier_lands(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    from app.main import app

    org = seeded_db["org"]
    rc = await _pending(db, org, tier="high")
    _install_actor(app, org, "org:admin", actor_id="user_ada")
    try:
        resp = await client.post(
            f"/api/v1/compliance/classifications/{rc.id}/approve",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == "user_ada"


@pytest.mark.asyncio
async def test_admin_can_reject(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    from app.main import app

    org = seeded_db["org"]
    rc = await _pending(db, org)
    _install_actor(app, org, "org:admin")
    try:
        resp = await client.post(
            f"/api/v1/compliance/classifications/{rc.id}/reject",
            json={"reason": "We do not use this for hiring decisions."},
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_deciding_twice_is_a_conflict(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    from app.main import app

    org = seeded_db["org"]
    rc = await _pending(db, org)
    _install_actor(app, org, "org:admin")
    try:
        first = await client.post(
            f"/api/v1/compliance/classifications/{rc.id}/approve",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
        second = await client.post(
            f"/api/v1/compliance/classifications/{rc.id}/approve",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert first.status_code == 200
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_unknown_classification_is_a_404(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        resp = await client.post(
            f"/api/v1/compliance/classifications/{uuid.uuid4()}/approve",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 404
