"""E2E: Manual baseline recompute endpoints + audit log diff structure."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.services.baseline_service import MIN_EVENTS


async def _ingest_events(client: AsyncClient, api_key: str, n: int) -> None:
    for i in range(n):
        resp = await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": f"Question {i}",
                "response": f"Answer {i}",
                "model": "gpt-4o",
                "latency_ms": 100,
                "token_count": 25,
                "tool_calls": [{"name": "search"}],
            },
            headers={"X-Parry-Secret": api_key},
        )
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_recompute_baseline_endpoint_writes_audit_diff(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """POST /agents/{id}/baseline/recompute returns the agent and writes
    an audit log entry containing the before/after baseline diff."""
    agent_id = str(seeded_db["agent"].id)
    api_key = seeded_db["api_key_raw"]

    # Seed enough events to satisfy MIN_EVENTS
    await _ingest_events(client, api_key, MIN_EVENTS)

    # Call recompute endpoint via Bearer auth
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/baseline/recompute",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    baseline = body["baseline"]
    assert baseline is not None
    assert baseline["event_count"] >= MIN_EVENTS
    assert baseline["quality"] in ("low", "medium", "high")
    # tool_stats from item 3
    assert "tool_stats" in baseline
    assert baseline["tool_stats"].get("search", {}).get("total_calls", 0) >= MIN_EVENTS

    # Audit log must contain a baseline.recomputed entry with before/after
    audit_rows = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "baseline.recomputed")))
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    entry = audit_rows[0]
    assert entry.resource_type == "agent"
    assert entry.resource_id == agent_id
    details = entry.details or {}
    assert "before" in details
    assert "after" in details
    # First recompute → before is None, after is populated
    assert details["before"] is None
    assert details["after"]["event_count"] >= MIN_EVENTS


@pytest.mark.asyncio
async def test_recompute_baseline_404_with_too_few_events(client: AsyncClient, seeded_db: dict):
    """When the agent has fewer than MIN_EVENTS, recompute returns 400."""
    agent_id = str(seeded_db["agent"].id)
    api_key = seeded_db["api_key_raw"]

    await _ingest_events(client, api_key, 5)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/baseline/recompute",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert "least" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_recompute_all_baselines_bulk_endpoint(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """POST /agents/baselines/recompute-all loops every agent in the org."""
    api_key = seeded_db["api_key_raw"]
    await _ingest_events(client, api_key, MIN_EVENTS)

    resp = await client.post(
        "/api/v1/agents/baselines/recompute-all",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    counts = resp.json()
    # 1 seeded agent with enough events → 1 recomputed
    assert counts["recomputed"] == 1
    assert counts["errored"] == 0

    # Bulk path uses reason=manual_bulk in the audit details
    audit_rows = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "baseline.recomputed")))
        .scalars()
        .all()
    )
    assert any((r.details or {}).get("reason") == "manual_bulk" for r in audit_rows)
