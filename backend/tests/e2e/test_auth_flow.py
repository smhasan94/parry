"""E2E: Auth boundary tests -- missing key, bad key, inactive key."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ingest_missing_key(client: AsyncClient):
    """Ingest without X-Parry-Secret should return 422 (missing header)."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={"agent_id": "test", "prompt": "hello"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_bad_key(client: AsyncClient):
    """Ingest with invalid API key should return 401."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={"agent_id": "test", "prompt": "hello"},
        headers={"X-Parry-Secret": "sk-parry-invalid-key-12345"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_incidents_no_auth(client: AsyncClient):
    """List incidents without auth should return 422."""
    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_incidents_bad_bearer(client: AsyncClient):
    """List incidents with bad bearer should return 401."""
    resp = await client.get(
        "/api/v1/incidents",
        headers={"Authorization": "Bearer sk-parry-fake-key-99999"},
    )
    assert resp.status_code == 401
