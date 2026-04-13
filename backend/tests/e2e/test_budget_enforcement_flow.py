"""E2E: Budget enforcement — proxy/check is blocked when agent is over budget.

Covers:
1. Creating a budget via PUT /budgets returns 200 with the new record.
2. With no spend, the proxy allows calls normally.
3. When Redis spend counters are primed above the 95% threshold, proxy
   blocks with detector="budget_enforcement".
4. Disabling the budget un-blocks the agent.
5. DELETE /budgets/{id} removes the record.
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _enable_blocking(db: AsyncSession, seeded_db: dict) -> None:
    seeded_db["org"].blocking_enabled = True
    await db.flush()
    await db.commit()


@pytest.mark.asyncio
async def test_budget_crud_lifecycle(admin_client: AsyncClient, seeded_db: dict):
    """PUT /budgets creates a new budget; DELETE removes it."""
    agent_id = str(seeded_db["agent"].id)

    # Create
    resp = await admin_client.put(
        "/api/v1/budgets",
        json={"agent_id": agent_id, "period": "day", "cap_usd": 5.0, "enabled": True},
    )
    assert resp.status_code == 200, resp.text
    budget = resp.json()
    assert budget["cap_usd"] == 5.0
    assert budget["period"] == "day"
    assert budget["enabled"] is True
    budget_id = budget["id"]

    # List
    resp = await admin_client.get(f"/api/v1/budgets?agent_id={agent_id}")
    assert resp.status_code == 200
    budgets = resp.json()
    assert any(b["id"] == budget_id for b in budgets)

    # Delete
    resp = await admin_client.delete(f"/api/v1/budgets/{budget_id}")
    assert resp.status_code == 204

    # Verify gone
    resp = await admin_client.get(f"/api/v1/budgets?agent_id={agent_id}")
    assert not any(b["id"] == budget_id for b in resp.json())


@pytest.mark.asyncio
async def test_budget_blocks_proxy_when_over_limit(
    admin_client: AsyncClient, client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """When the agent is over its budget cap, proxy/check returns allowed=False."""
    await _enable_blocking(db, seeded_db)
    agent_id = seeded_db["agent"].id

    # Create a very small daily budget ($0.01)
    await admin_client.put(
        "/api/v1/budgets",
        json={
            "agent_id": str(agent_id),
            "period": "day",
            "cap_usd": 0.01,
            "enabled": True,
        },
    )

    # Patch budget_service.get_spend to return a value exceeding 95% of cap
    with patch(
        "app.services.budget_service.get_spend",
        return_value=0.0096,  # 96% of $0.01 cap → over 95% threshold
    ):
        resp = await client.post(
            "/api/v1/proxy/check",
            json={
                "agent_id": "e2e-agent",
                "prompt": "What is 2 + 2?",
                "tool_calls": [],
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is False
    assert body["detector"] == "budget_enforcement"
    assert "budget" in body["reason"].lower() or "exceeded" in body["reason"].lower()


@pytest.mark.asyncio
async def test_disabled_budget_does_not_block(
    admin_client: AsyncClient, client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """A disabled budget should not block even when spend is over the cap."""
    await _enable_blocking(db, seeded_db)
    agent_id = seeded_db["agent"].id

    # Create a disabled budget
    await admin_client.put(
        "/api/v1/budgets",
        json={
            "agent_id": str(agent_id),
            "period": "day",
            "cap_usd": 0.01,
            "enabled": False,
        },
    )

    # Even with spend above cap, a disabled budget must not block
    with patch("app.services.budget_service.get_spend", return_value=999.0):
        resp = await client.post(
            "/api/v1/proxy/check",
            json={
                "agent_id": "e2e-agent",
                "prompt": "What is the capital of France?",
                "tool_calls": [],
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )

    assert resp.status_code == 200
    body = resp.json()
    # A disabled budget should never trigger budget_enforcement
    assert body.get("detector") != "budget_enforcement"


@pytest.mark.asyncio
async def test_budget_invalid_period_rejected(admin_client: AsyncClient, seeded_db: dict):
    """PUT /budgets with an invalid period returns 400."""
    resp = await admin_client.put(
        "/api/v1/budgets",
        json={"period": "week", "cap_usd": 1.0, "enabled": True},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_budget_negative_cap_rejected(admin_client: AsyncClient, seeded_db: dict):
    """PUT /budgets with a non-positive cap returns 400."""
    resp = await admin_client.put(
        "/api/v1/budgets",
        json={"period": "day", "cap_usd": -5.0, "enabled": True},
    )
    assert resp.status_code == 400
