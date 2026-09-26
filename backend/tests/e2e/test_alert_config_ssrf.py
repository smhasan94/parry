"""SSRF checks on alert config's customer-supplied webhook targets.

Pydantic's HttpUrl on AlertConfigUpdate already rejects a malformed
URL; it does not and cannot reject a well-formed one that points at
169.254.169.254 or an internal host. That is this test's job.
"""

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
