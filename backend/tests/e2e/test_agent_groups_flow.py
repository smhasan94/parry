"""E2E: Agent groups — CRUD + agent assignment."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_group_lifecycle(admin_client: AsyncClient, seeded_db: dict):
    """Create group → assign agent → verify → unassign → delete."""
    agent_id = str(seeded_db["agent"].id)

    # 1. Create group
    resp = await admin_client.post(
        "/api/v1/agent-groups",
        json={
            "name": "Production Agents",
            "description": "Customer-facing production agents",
        },
    )
    assert resp.status_code == 201, resp.text
    group = resp.json()
    group_id = group["id"]
    assert group["name"] == "Production Agents"
    assert group["agent_count"] == 0

    # 2. List groups
    resp = await admin_client.get("/api/v1/agent-groups")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 3. Get group
    resp = await admin_client.get(f"/api/v1/agent-groups/{group_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Production Agents"

    # 4. Assign agent to group
    resp = await admin_client.patch(
        f"/api/v1/agent-groups/{group_id}/agents/{agent_id}",
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent_id

    # 5. Verify group has agent
    resp = await admin_client.get(f"/api/v1/agent-groups/{group_id}")
    assert resp.status_code == 200
    assert resp.json()["agent_count"] == 1

    # 6. Unassign agent
    resp = await admin_client.delete(
        f"/api/v1/agent-groups/{group_id}/agents/{agent_id}"
    )
    assert resp.status_code == 204

    # 7. Delete group
    resp = await admin_client.delete(f"/api/v1/agent-groups/{group_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_duplicate_group_name(admin_client: AsyncClient, seeded_db: dict):
    """Creating two groups with same name should fail."""
    resp = await admin_client.post(
        "/api/v1/agent-groups",
        json={"name": "Unique Name"},
    )
    assert resp.status_code == 201

    resp = await admin_client.post(
        "/api/v1/agent-groups",
        json={"name": "Unique Name"},
    )
    assert resp.status_code == 409
