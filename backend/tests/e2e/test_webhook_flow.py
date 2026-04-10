"""E2E: Webhook endpoints — CRUD, event type validation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_webhook_endpoint_lifecycle(admin_client: AsyncClient, seeded_db: dict):
    """Create → list → update → delete webhook endpoint."""
    # 1. Create endpoint
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={
            "url": "https://example.com/webhook",
            "event_types": ["detection.triggered", "incident.created"],
            "description": "E2E test endpoint",
        },
    )
    assert resp.status_code == 201, resp.text
    endpoint = resp.json()
    endpoint_id = endpoint["id"]
    assert endpoint["url"] == "https://example.com/webhook"
    assert len(endpoint["event_types"]) == 2
    assert endpoint["secret"].startswith("whsec_")
    assert endpoint["failure_count"] == 0

    # 2. List endpoints
    resp = await admin_client.get("/api/v1/webhooks/endpoints")
    assert resp.status_code == 200
    endpoints = resp.json()
    assert len(endpoints) >= 1

    # 3. Update endpoint
    resp = await admin_client.patch(
        f"/api/v1/webhooks/endpoints/{endpoint_id}",
        json={"description": "Updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"

    # 4. Check delivery history (empty)
    resp = await admin_client.get(
        f"/api/v1/webhooks/endpoints/{endpoint_id}/deliveries"
    )
    assert resp.status_code == 200
    assert resp.json() == []

    # 5. Delete endpoint
    resp = await admin_client.delete(f"/api/v1/webhooks/endpoints/{endpoint_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_webhook_invalid_event_type(admin_client: AsyncClient, seeded_db: dict):
    """Creating endpoint with invalid event type should fail."""
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={
            "url": "https://example.com/webhook",
            "event_types": ["invalid.event"],
        },
    )
    assert resp.status_code == 400
    assert "Invalid event types" in resp.json()["detail"]
