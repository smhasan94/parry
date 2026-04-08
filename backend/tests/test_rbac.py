"""Unit tests for the RBAC module — role resolution + require_role gate."""

import pytest
from fastapi import HTTPException

from app.core.dependencies import Actor
from app.core.rbac import Role, actor_role, require_role
from app.db.models import Org


def _owner() -> Actor:
    return Actor(actor_type="user", actor_id="u1", label="o", clerk_role="org:owner")


def _admin() -> Actor:
    return Actor(actor_type="user", actor_id="u2", label="a", clerk_role="org:admin")


def _viewer() -> Actor:
    return Actor(actor_type="user", actor_id="u3", label="v", clerk_role="org:viewer")


def _api_key() -> Actor:
    return Actor(actor_type="api_key", actor_id="k1", label="sdk-key")


def _system() -> Actor:
    return Actor(actor_type="system", actor_id=None, label="baseline-refresh")


ORG = Org(id="00000000-0000-0000-0000-000000000000", name="test")


# ── actor_role() resolution ──────────────────────────────────────────


def test_owner_resolves_to_owner():
    assert actor_role(_owner()) == Role.OWNER


def test_admin_resolves_to_admin():
    assert actor_role(_admin()) == Role.ADMIN


def test_viewer_resolves_to_viewer():
    assert actor_role(_viewer()) == Role.VIEWER


def test_api_key_is_always_admin():
    assert actor_role(_api_key()) == Role.ADMIN


def test_system_actor_is_owner():
    assert actor_role(_system()) == Role.OWNER


def test_missing_clerk_role_defaults_to_viewer():
    """No role claim in JWT → VIEWER. Secure default, never fail-open."""
    bare = Actor(actor_type="user", actor_id="u", label="u", clerk_role=None)
    assert actor_role(bare) == Role.VIEWER


def test_unknown_clerk_role_defaults_to_viewer():
    """Unknown role string (Clerk adds a new tier we don't know about)
    must downgrade to VIEWER rather than being treated as permissive."""
    weird = Actor(actor_type="user", actor_id="u", label="u", clerk_role="org:superadmin")
    assert actor_role(weird) == Role.VIEWER


# ── require_role() gate ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_admin_passes_for_owner():
    gate = require_role(Role.ADMIN)
    result = await gate(actor_tuple=(ORG, _owner()))
    assert result[1].clerk_role == "org:owner"


@pytest.mark.asyncio
async def test_require_admin_passes_for_admin():
    gate = require_role(Role.ADMIN)
    result = await gate(actor_tuple=(ORG, _admin()))
    assert result[1].clerk_role == "org:admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_viewer():
    gate = require_role(Role.ADMIN)
    with pytest.raises(HTTPException) as exc:
        await gate(actor_tuple=(ORG, _viewer()))
    assert exc.value.status_code == 403
    assert "admin" in exc.value.detail.lower()
    assert exc.value.headers.get("X-Required-Role") == "admin"


@pytest.mark.asyncio
async def test_require_owner_rejects_admin():
    gate = require_role(Role.OWNER)
    with pytest.raises(HTTPException) as exc:
        await gate(actor_tuple=(ORG, _admin()))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_viewer_passes_for_anyone():
    gate = require_role(Role.VIEWER)
    for actor in (_owner(), _admin(), _viewer(), _api_key(), _system()):
        result = await gate(actor_tuple=(ORG, actor))
        assert result is not None


@pytest.mark.asyncio
async def test_api_key_passes_admin_gate():
    """API keys are always ADMIN — verify an API key actor passes an
    ADMIN gate but fails an OWNER gate."""
    admin_gate = require_role(Role.ADMIN)
    owner_gate = require_role(Role.OWNER)

    result = await admin_gate(actor_tuple=(ORG, _api_key()))
    assert result[1].actor_type == "api_key"

    with pytest.raises(HTTPException) as exc:
        await owner_gate(actor_tuple=(ORG, _api_key()))
    assert exc.value.status_code == 403
