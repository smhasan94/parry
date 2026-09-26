"""SSRF checks on alert config's customer-supplied webhook targets.

Pydantic's HttpUrl on AlertConfigUpdate already rejects a malformed
URL; it does not and cannot reject a well-formed one that points at
169.254.169.254 or an internal host. That is this test's job.
"""

import threading

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rejects_a_private_webhook_url(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"webhook_url": "https://169.254.169.254/hook"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_rejects_a_private_slack_webhook_url(
    admin_client: AsyncClient, seeded_db: dict
) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"slack_webhook_url": "https://10.0.0.5/hook"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_accepts_a_public_webhook_url(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"webhook_url": "https://example.com/hook"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["webhook_url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_update_resolves_off_the_event_loop(
    admin_client: AsyncClient, seeded_db: dict, resolver_thread_ids: list[int]
) -> None:
    # update_alert_config runs on uvicorn's loop; a slow nameserver for the
    # customer's hostname must not stall every other tenant's requests.
    resp = await admin_client.put(
        "/api/v1/alerts",
        json={
            "slack_webhook_url": "https://hooks.example/slack",
            "webhook_url": "https://hooks.example/hook",
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(resolver_thread_ids) == 2
    assert threading.get_ident() not in resolver_thread_ids
