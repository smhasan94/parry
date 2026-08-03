"""Probe credential endpoints.

The endpoint contract that matters: a token can be written and rotated,
and can never be read back — not on create, not on list, not on fetch.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secret_crypto
from app.core.dependencies import Actor, get_current_actor, get_current_org

SECRET = "00Ab-super-secret-okta-token"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        secret_crypto.settings, "probe_encryption_key", secret_crypto.generate_key()
    )


def _install_actor(app, org, clerk_role: str | None):
    actor = Actor(actor_type="user", actor_id="u-ops", label="ada@corp.com", clerk_role=clerk_role)

    async def _actor_override():
        return (org, actor)

    async def _org_override():
        return org

    app.dependency_overrides[get_current_actor] = _actor_override
    app.dependency_overrides[get_current_org] = _org_override


def _clear(app):
    app.dependency_overrides.pop(get_current_actor, None)
    app.dependency_overrides.pop(get_current_org, None)


_BODY = {
    "probe_type": "sso",
    "provider": "okta",
    "label": "Acme Okta",
    "secret": SECRET,
    "config": {"okta_domain": "acme.okta.com"},
}


@pytest.mark.asyncio
async def test_admin_can_register_a_credential(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        resp = await client.post(
            "/api/v1/discovery/credentials",
            json=_BODY,
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 201
    assert resp.json()["label"] == "Acme Okta"


@pytest.mark.asyncio
async def test_the_secret_is_never_returned(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        created = await client.post(
            "/api/v1/discovery/credentials",
            json=_BODY,
            headers={"Authorization": "Bearer dummy-jwt"},
        )
        listed = await client.get(
            "/api/v1/discovery/credentials",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    # Neither the plaintext nor the ciphertext should leave the server.
    for body in (created.text, listed.text):
        assert SECRET not in body
        assert "encrypted_secret" not in body


@pytest.mark.asyncio
async def test_viewer_cannot_register_a_credential(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:viewer")
    try:
        resp = await client.post(
            "/api/v1/discovery/credentials",
            json=_BODY,
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_non_okta_host_is_rejected(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        resp = await client.post(
            "/api/v1/discovery/credentials",
            json={**_BODY, "config": {"okta_domain": "169.254.169.254"}},
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    # A stored host becomes an unattended outbound request later.
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_credential_can_be_deleted(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        created = await client.post(
            "/api/v1/discovery/credentials",
            json=_BODY,
            headers={"Authorization": "Bearer dummy-jwt"},
        )
        cred_id = created.json()["id"]
        deleted = await client.delete(
            f"/api/v1/discovery/credentials/{cred_id}",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
        listed = await client.get(
            "/api/v1/discovery/credentials",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert deleted.status_code == 204
    assert cred_id not in [c["id"] for c in listed.json()]


@pytest.mark.asyncio
async def test_deleting_an_unknown_credential_is_a_404(client: AsyncClient, seeded_db: dict):
    from app.main import app

    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        resp = await client.delete(
            f"/api/v1/discovery/credentials/{uuid.uuid4()}",
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_registering_without_an_encryption_key_is_a_503(
    client: AsyncClient, seeded_db: dict, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
):
    from app.main import app

    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "")
    _install_actor(app, seeded_db["org"], "org:admin")
    try:
        resp = await client.post(
            "/api/v1/discovery/credentials",
            json=_BODY,
            headers={"Authorization": "Bearer dummy-jwt"},
        )
    finally:
        _clear(app)

    # Unconfigured deployment, not a bad request — and definitely not a
    # 500 that leaves the operator guessing.
    assert resp.status_code == 503
