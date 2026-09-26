"""SSRF checks on webhook endpoint create/update.

An org ADMIN sets this URL and Parry's own backend POSTs to it on a
schedule — the same stored-SSRF shape as an MCP server URL, but for a
customer notification target rather than a tool source.
"""

import threading

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_rejects_a_private_target(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://169.254.169.254/hook", "event_types": []},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_create_rejects_http(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "http://example.com/hook", "event_types": []},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_create_accepts_a_public_target(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://example.com/hook", "event_types": []},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_update_rejects_repointing_at_a_private_target(
    admin_client: AsyncClient, seeded_db: dict
) -> None:
    create = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://example.com/hook", "event_types": []},
    )
    endpoint_id = create.json()["id"]

    resp = await admin_client.patch(
        f"/api/v1/webhooks/endpoints/{endpoint_id}",
        json={"url": "https://10.0.0.5/hook"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


# ── Off-loop resolution ───────────────────────────────────────────
# Create/update run on uvicorn's loop; resolving a customer's hostname
# there would stall every tenant's requests on a slow nameserver.


@pytest.mark.asyncio
async def test_create_resolves_off_the_event_loop(
    admin_client: AsyncClient, seeded_db: dict, resolver_thread_ids: list[int]
) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://hooks.example/hook", "event_types": []},
    )
    assert resp.status_code == 201, resp.text
    assert resolver_thread_ids, "resolver was never called"
    assert threading.get_ident() not in resolver_thread_ids


@pytest.mark.asyncio
async def test_update_resolves_off_the_event_loop(
    admin_client: AsyncClient, seeded_db: dict, resolver_thread_ids: list[int]
) -> None:
    create = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://hooks.example/hook", "event_types": []},
    )
    endpoint_id = create.json()["id"]
    resolver_thread_ids.clear()

    resp = await admin_client.patch(
        f"/api/v1/webhooks/endpoints/{endpoint_id}",
        json={"url": "https://hooks.example/other"},
    )
    assert resp.status_code == 200, resp.text
    assert resolver_thread_ids, "resolver was never called"
    assert threading.get_ident() not in resolver_thread_ids
