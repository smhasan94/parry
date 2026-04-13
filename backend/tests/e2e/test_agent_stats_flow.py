"""E2E: Agent stats endpoint and health score on agent responses.

Covers:
1. GET /agents/{id}/stats returns the expected keys for each window.
2. GET /agents/{id} includes health_score / health_grade fields.
3. Stats for an unknown agent return 404.
4. Stats window validation rejects bad values.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_stats_returns_expected_keys(
    admin_client: AsyncClient, seeded_db: dict
):
    """Stats endpoint returns all required top-level keys."""
    agent_id = str(seeded_db["agent"].id)

    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/stats?window=30d")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Core keys the UI charts depend on
    assert "event_volume" in body
    assert "tool_calls" in body
    assert "model_usage" in body
    assert "anomaly_trend" in body
    assert "detection_counts" in body


@pytest.mark.asyncio
async def test_agent_stats_7d_and_90d_windows(
    admin_client: AsyncClient, seeded_db: dict
):
    """All three time-windows succeed and return the same shape."""
    agent_id = str(seeded_db["agent"].id)

    for window in ("7d", "30d", "90d"):
        resp = await admin_client.get(f"/api/v1/agents/{agent_id}/stats?window={window}")
        assert resp.status_code == 200, f"window={window} failed: {resp.text}"
        body = resp.json()
        assert "event_volume" in body


@pytest.mark.asyncio
async def test_agent_stats_invalid_window(
    admin_client: AsyncClient, seeded_db: dict
):
    """A bad window value should be rejected (422 or 400)."""
    agent_id = str(seeded_db["agent"].id)
    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/stats?window=1y")
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_agent_stats_wrong_org_404(
    admin_client: AsyncClient, seeded_db: dict
):
    """Requesting stats for a non-existent agent returns 404."""
    import uuid

    resp = await admin_client.get(f"/api/v1/agents/{uuid.uuid4()}/stats")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_agent_includes_health_score(
    admin_client: AsyncClient, seeded_db: dict
):
    """GET /agents/{id} response carries health_score and health_grade."""
    agent_id = str(seeded_db["agent"].id)

    resp = await admin_client.get(f"/api/v1/agents/{agent_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # health_score may be None for an agent with no events, but the
    # key must be present in the response.
    assert "health_score" in body
    assert "health_grade" in body


@pytest.mark.asyncio
async def test_list_agents_includes_health_fields(
    admin_client: AsyncClient, seeded_db: dict
):
    """GET /agents list returns health_score / health_grade on each item."""
    resp = await admin_client.get("/api/v1/agents")
    assert resp.status_code == 200, resp.text
    agents = resp.json()
    assert len(agents) >= 1

    for agent in agents:
        assert "health_score" in agent
        assert "health_grade" in agent
