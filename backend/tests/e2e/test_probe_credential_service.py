"""Storing and using probe credentials.

The invariant under test throughout: the plaintext token goes in, and the
only way back out is an explicit decrypt for an outbound call. It must
never survive in the row, a response, or a log line.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secret_crypto
from app.core.exceptions import ConfigurationError, NotFoundError
from app.db.models import Org
from app.services import probe_credential_service as svc


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        secret_crypto.settings, "probe_encryption_key", secret_crypto.generate_key()
    )


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Acme", clerk_org_id=f"c_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


@pytest.mark.asyncio
async def test_the_token_is_not_stored_in_plaintext(db: AsyncSession):
    org = await _org(db)

    cred = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="00Ab-super-secret-token",
        config={"okta_domain": "acme.okta.com"},
    )

    assert "00Ab-super-secret-token" not in cred.encrypted_secret
    assert cred.encrypted_secret != "00Ab-super-secret-token"


@pytest.mark.asyncio
async def test_the_token_can_be_recovered_for_an_outbound_call(db: AsyncSession):
    org = await _org(db)
    cred = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="00Ab-super-secret-token",
        config={"okta_domain": "acme.okta.com"},
    )

    assert svc.reveal_secret(cred) == "00Ab-super-secret-token"


@pytest.mark.asyncio
async def test_creating_without_an_encryption_key_is_refused(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    org = await _org(db)
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "")

    # Better to reject the credential than to persist it in the clear.
    with pytest.raises(ConfigurationError):
        await svc.create(
            db,
            org_id=org.id,
            probe_type="sso",
            provider="okta",
            label="Acme Okta",
            secret="00Ab-super-secret-token",
            config={"okta_domain": "acme.okta.com"},
        )


@pytest.mark.asyncio
async def test_listing_is_scoped_to_the_org(db: AsyncSession):
    mine, theirs = await _org(db), await _org(db)
    for org in (mine, theirs):
        await svc.create(
            db,
            org_id=org.id,
            probe_type="sso",
            provider="okta",
            label="theirs",
            secret="tok",
            config={"okta_domain": "acme.okta.com"},
        )

    assert len(await svc.list_for_org(db, org_id=mine.id)) == 1


@pytest.mark.asyncio
async def test_another_orgs_credential_cannot_be_fetched(db: AsyncSession):
    mine, theirs = await _org(db), await _org(db)
    cred = await svc.create(
        db,
        org_id=theirs.id,
        probe_type="sso",
        provider="okta",
        label="theirs",
        secret="tok",
        config={"okta_domain": "acme.okta.com"},
    )

    with pytest.raises(NotFoundError):
        await svc.get(db, org_id=mine.id, credential_id=cred.id)


@pytest.mark.asyncio
async def test_deleting_removes_the_ciphertext(db: AsyncSession):
    org = await _org(db)
    cred = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="tok",
        config={"okta_domain": "acme.okta.com"},
    )

    await svc.delete(db, org_id=org.id, credential_id=cred.id)

    with pytest.raises(NotFoundError):
        await svc.get(db, org_id=org.id, credential_id=cred.id)


@pytest.mark.asyncio
async def test_rotating_replaces_the_stored_token(db: AsyncSession):
    org = await _org(db)
    cred = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="old-token",
        config={"okta_domain": "acme.okta.com"},
    )
    before = cred.encrypted_secret

    rotated = await svc.rotate_secret(db, org_id=org.id, credential_id=cred.id, secret="new-token")

    assert rotated.encrypted_secret != before
    assert svc.reveal_secret(rotated) == "new-token"


@pytest.mark.asyncio
async def test_sync_outcome_is_recorded_for_operators(db: AsyncSession):
    org = await _org(db)
    cred = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="Acme Okta",
        secret="tok",
        config={"okta_domain": "acme.okta.com"},
    )

    await svc.record_sync(db, cred, status="ok", error=None)
    assert cred.last_sync_status == "ok"
    assert cred.last_sync_at is not None
    assert cred.last_sync_error is None

    await svc.record_sync(db, cred, status="failed", error="401 Unauthorized")
    assert cred.last_sync_status == "failed"
    assert cred.last_sync_error == "401 Unauthorized"


@pytest.mark.asyncio
async def test_only_active_credentials_are_due_for_sync(db: AsyncSession):
    org = await _org(db)
    active = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="active",
        secret="tok",
        config={"okta_domain": "acme.okta.com"},
    )
    disabled = await svc.create(
        db,
        org_id=org.id,
        probe_type="sso",
        provider="okta",
        label="disabled",
        secret="tok",
        config={"okta_domain": "other.okta.com"},
    )
    disabled.is_active = False
    await db.flush()

    due = await svc.list_due_for_sync(db)

    ids = {c.id for c in due}
    assert active.id in ids
    assert disabled.id not in ids


@pytest.mark.asyncio
async def test_a_stored_okta_domain_is_validated_on_the_way_in(db: AsyncSession):
    org = await _org(db)

    # The worker will fetch this host with a token attached. Rejecting it
    # at write time means a bad row can never become an SSRF at sync time.
    with pytest.raises(ValueError):
        await svc.create(
            db,
            org_id=org.id,
            probe_type="sso",
            provider="okta",
            label="evil",
            secret="tok",
            config={"okta_domain": "169.254.169.254"},
        )
