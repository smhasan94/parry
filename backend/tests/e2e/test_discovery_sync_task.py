"""The scheduled discovery sync.

This runs unattended across every tenant, so the behaviours that matter
are not the happy path: one org's broken credential must not stop
another's sync, a revoked token must leave a visible trace rather than a
silent no-op, and a decryption failure must never fall back to skipping
encryption.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secret_crypto
from app.db.models import Org
from app.services import probe_credential_service as creds
from app.workers.discovery_sync_task import sync_all_credentials, sync_one_credential

_OKTA_PAYLOAD = [
    {
        "app": {
            "id": "0oa1notion",
            "label": "Notion AI",
            "status": "ACTIVE",
            "created": "2026-01-15T10:00:00.000Z",
        },
        "users": [{"profile": {"login": "ada@corp.com"}}],
    }
]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        secret_crypto.settings, "probe_encryption_key", secret_crypto.generate_key()
    )


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Acme", clerk_org_id=f"w_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _cred(db: AsyncSession, org: Org, *, domain: str = "acme.okta.com"):
    return await creds.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="00Ab-token",
        config={"okta_domain": domain},
    )


@pytest.mark.asyncio
async def test_a_successful_sync_records_ok(db: AsyncSession):
    org = await _org(db)
    cred = await _cred(db, org)

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(return_value=_OKTA_PAYLOAD),
    ):
        result = await sync_one_credential(db, cred)

    assert result["status"] == "ok"
    assert cred.last_sync_status == "ok"
    assert cred.last_sync_error is None
    assert cred.last_sync_at is not None


@pytest.mark.asyncio
async def test_the_sync_uses_the_stored_token_and_domain(db: AsyncSession):
    org = await _org(db)
    cred = await _cred(db, org, domain="acme.okta.com")

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(return_value=_OKTA_PAYLOAD),
    ) as fetch:
        await sync_one_credential(db, cred)

    assert fetch.await_args.kwargs["okta_domain"] == "acme.okta.com"
    assert fetch.await_args.kwargs["api_token"] == "00Ab-token"


@pytest.mark.asyncio
async def test_a_revoked_token_is_recorded_rather_than_swallowed(db: AsyncSession):
    import httpx

    org = await _org(db)
    cred = await _cred(db, org)
    request = httpx.Request("GET", "https://acme.okta.com/api/v1/apps")
    error = httpx.HTTPStatusError(
        "401", request=request, response=httpx.Response(401, request=request)
    )

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(side_effect=error),
    ):
        result = await sync_one_credential(db, cred)

    # A silent failure is indistinguishable from "nothing new was found",
    # and the register would rot without anyone noticing.
    assert result["status"] == "failed"
    assert cred.last_sync_status == "failed"
    assert cred.last_sync_error


@pytest.mark.asyncio
async def test_the_recorded_error_does_not_contain_the_token(db: AsyncSession):
    import httpx

    org = await _org(db)
    cred = await _cred(db, org)
    error = httpx.HTTPError("connect failed for token 00Ab-token")

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(side_effect=error),
    ):
        await sync_one_credential(db, cred)

    assert "00Ab-token" not in (cred.last_sync_error or "")


@pytest.mark.asyncio
async def test_one_broken_credential_does_not_stop_the_others(db: AsyncSession):
    import httpx

    broken_org, healthy_org = await _org(db), await _org(db)
    broken = await _cred(db, broken_org, domain="broken.okta.com")
    healthy = await _cred(db, healthy_org, domain="healthy.okta.com")
    await db.commit()

    async def _fetch(*, okta_domain: str, api_token: str):
        if okta_domain == "broken.okta.com":
            raise httpx.HTTPError("boom")
        return _OKTA_PAYLOAD

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(side_effect=_fetch),
    ):
        summary = await sync_all_credentials(db)

    assert summary["synced"] >= 1
    assert summary["failed"] >= 1
    await db.refresh(broken)
    await db.refresh(healthy)
    assert broken.last_sync_status == "failed"
    assert healthy.last_sync_status == "ok"


@pytest.mark.asyncio
async def test_an_undecryptable_credential_fails_that_credential_only(db: AsyncSession):
    org = await _org(db)
    cred = await _cred(db, org)
    # Simulates a key rotated without re-encryption, or a row from
    # another environment.
    cred.encrypted_secret = "gAAAAABmnot-a-valid-token"
    await db.flush()

    result = await sync_one_credential(db, cred)

    assert result["status"] == "failed"
    assert cred.last_sync_status == "failed"


@pytest.mark.asyncio
async def test_disabled_credentials_are_skipped(db: AsyncSession):
    org = await _org(db)
    cred = await _cred(db, org)
    cred.is_active = False
    await db.commit()

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(return_value=_OKTA_PAYLOAD),
    ) as fetch:
        await sync_all_credentials(db)

    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_resyncing_the_same_grants_creates_no_duplicates(db: AsyncSession):
    from app.services import discovery_service

    org = await _org(db)
    cred = await _cred(db, org)

    with patch(
        "app.workers.discovery_sync_task.fetch_okta_apps_and_users",
        new=AsyncMock(return_value=_OKTA_PAYLOAD),
    ):
        await sync_one_credential(db, cred)
        first = len(await discovery_service.list_shadow_systems(db, org_id=org.id))
        await sync_one_credential(db, cred)
        second = len(await discovery_service.list_shadow_systems(db, org_id=org.id))

    # The whole point of running on a schedule: it has to be safe to run
    # every night forever.
    assert first == second
