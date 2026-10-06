"""E2E: synchronous response scan flow via POST /api/v1/proxy/scan-response.

Covers the 4 response-scanning cases. Skipped locally without docker-postgres,
runs in CI alongside the rest of the e2e suite.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResponseScanMode


async def _set_mode(db: AsyncSession, seeded_db: dict, mode: ResponseScanMode) -> None:
    seeded_db["org"].response_scan_mode = mode
    await db.flush()
    await db.commit()


@pytest.mark.asyncio
async def test_off_mode_returns_response_unchanged(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    await _set_mode(db, seeded_db, ResponseScanMode.OFF)

    body = {
        "agent_id": "e2e-agent",
        "response": "Here is an SSN: 123-45-6789",
    }
    resp = await client.post(
        "/api/v1/proxy/scan-response",
        json=body,
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["blocked"] is False
    assert data["response"] == body["response"]
    assert data["mode"] == "off"


@pytest.mark.asyncio
async def test_redact_mode_strips_ssn(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    await _set_mode(db, seeded_db, ResponseScanMode.REDACT)

    resp = await client.post(
        "/api/v1/proxy/scan-response",
        json={
            "agent_id": "e2e-agent",
            "response": "SSN on file: 123-45-6789, name: Alice",
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["blocked"] is False
    assert "123-45-6789" not in data["response"]
    assert "[REDACTED:SSN_DETECTED]" in data["response"]
    assert data["mode"] == "redact"
    assert len(data["findings"]) >= 1


@pytest.mark.asyncio
async def test_block_mode_rejects_api_key(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    await _set_mode(db, seeded_db, ResponseScanMode.BLOCK)

    resp = await client.post(
        "/api/v1/proxy/scan-response",
        json={
            "agent_id": "e2e-agent",
            "response": 'your api_key: "sk-abcdefghijklmnopqrstuvwxyz1234"',
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["blocked"] is True
    assert data["response"] is None
    assert data["mode"] == "block"
    assert data["findings"]


@pytest.mark.asyncio
async def test_block_mode_clean_response_passes(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    await _set_mode(db, seeded_db, ResponseScanMode.BLOCK)

    resp = await client.post(
        "/api/v1/proxy/scan-response",
        json={
            "agent_id": "e2e-agent",
            "response": "Paris is the capital of France.",
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["blocked"] is False
    assert data["response"] == "Paris is the capital of France."
    assert data["findings"] == []
