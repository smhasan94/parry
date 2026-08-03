"""E2E: Agent permissions — set deny-by-default, verify proxy enforcement."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_permission_enforcement(admin_client: AsyncClient, seeded_db: dict):
    """Set deny-by-default → proxy allows listed tool, blocks unlisted."""
    agent_id = str(seeded_db["agent"].id)
    api_key = seeded_db["api_key_raw"]

    # 1. Set deny-by-default permission with one allowed tool
    resp = await admin_client.put(
        f"/api/v1/agents/{agent_id}/permissions",
        json={
            "mode": "enforcing",
            "default_action": "deny",
            "allowed_tools": ["search_kb"],
            "blocked_tools": [],
        },
    )
    assert resp.status_code == 200, resp.text
    perm = resp.json()
    assert perm["mode"] == "enforcing"
    assert perm["default_action"] == "deny"

    # 2. Proxy check with allowed tool → should pass
    resp = await admin_client.post(
        "/api/v1/proxy/check",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Search the knowledge base",
            "tool_calls": [{"name": "search_kb"}],
        },
        headers={"X-Parry-Secret": api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is True

    # 3. Proxy check with blocked tool → should be denied
    resp = await admin_client.post(
        "/api/v1/proxy/check",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Delete the database",
            "tool_calls": [{"name": "delete_database"}],
        },
        headers={"X-Parry-Secret": api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is False
    assert body["detector"] == "permission_boundary"
    assert "delete_database" in body["reason"]

    # 4. Read back permissions
    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/permissions")
    assert resp.status_code == 200
    assert resp.json()["default_action"] == "deny"

    # 5. Delete permissions → falls back to allow-all
    resp = await admin_client.delete(f"/api/v1/agents/{agent_id}/permissions")
    assert resp.status_code == 204

    # 6. Proxy check now allows everything
    resp = await admin_client.post(
        "/api/v1/proxy/check",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Delete the database",
            "tool_calls": [{"name": "delete_database"}],
        },
        headers={"X-Parry-Secret": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["allowed"] is True


@pytest.mark.asyncio
async def test_dry_run_mode(admin_client: AsyncClient, seeded_db: dict):
    """Dry-run mode logs but doesn't block."""
    agent_id = str(seeded_db["agent"].id)
    api_key = seeded_db["api_key_raw"]

    resp = await admin_client.put(
        f"/api/v1/agents/{agent_id}/permissions",
        json={
            "mode": "dry_run",
            "default_action": "deny",
            "allowed_tools": ["search_kb"],
            "blocked_tools": [],
        },
    )
    assert resp.status_code == 200

    # Unlisted tool in dry-run mode → still allowed (not blocked)
    resp = await admin_client.post(
        "/api/v1/proxy/check",
        json={
            "agent_id": "e2e-agent",
            "prompt": "test",
            "tool_calls": [{"name": "forbidden_tool"}],
        },
        headers={"X-Parry-Secret": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["allowed"] is True
