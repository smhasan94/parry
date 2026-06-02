"""Unit tests for policy_service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models import Policy
from app.services import policy_service


def _make_policy(org_id: uuid.UUID | None = None) -> Policy:
    return Policy(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        name="Default Policy",
        is_active=True,
    )


def _scalars_returning(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_one_or_none(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


# ── list_policies ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_policies_returns_all_for_org() -> None:
    org_id = uuid.uuid4()
    policies = [_make_policy(org_id), _make_policy(org_id)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(policies)

    result = await policy_service.list_policies(db, org_id)

    assert result == policies


@pytest.mark.asyncio
async def test_list_policies_returns_empty_list_for_unknown_org() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    result = await policy_service.list_policies(db, uuid.uuid4())

    assert result == []


# ── get_policy ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_policy_returns_policy() -> None:
    org_id = uuid.uuid4()
    policy = _make_policy(org_id)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(policy)

    result = await policy_service.get_policy(db, org_id, policy.id)

    assert result is policy


@pytest.mark.asyncio
async def test_get_policy_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await policy_service.get_policy(db, uuid.uuid4(), uuid.uuid4())


# ── create_policy ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_policy_creates_and_flushes() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await policy_service.create_policy(db, org_id, name="Strict Policy")

    assert result.org_id == org_id
    assert result.name == "Strict Policy"
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_policy_passes_kwargs_through() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await policy_service.create_policy(
        db,
        org_id,
        name="Tool Policy",
        allowed_tools=["search", "browse"],
        blocked_domains=["evil.com"],
        max_token_budget=10000,
    )

    assert result.allowed_tools == ["search", "browse"]
    assert result.blocked_domains == ["evil.com"]
    assert result.max_token_budget == 10000


# ── update_policy ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_policy_sets_fields() -> None:
    org_id = uuid.uuid4()
    policy = _make_policy(org_id)
    policy.name = "Old Name"
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(policy)

    result = await policy_service.update_policy(db, org_id, policy.id, name="New Name")

    assert result.name == "New Name"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_policy_skips_none_values() -> None:
    org_id = uuid.uuid4()
    policy = _make_policy(org_id)
    policy.description = "original"
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(policy)

    await policy_service.update_policy(db, org_id, policy.id, description=None)

    assert policy.description == "original"


@pytest.mark.asyncio
async def test_update_policy_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await policy_service.update_policy(db, uuid.uuid4(), uuid.uuid4(), name="x")


# ── delete_policy ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_policy_calls_delete_and_flush() -> None:
    org_id = uuid.uuid4()
    policy = _make_policy(org_id)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(policy)

    await policy_service.delete_policy(db, org_id, policy.id)

    db.delete.assert_awaited_once_with(policy)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_policy_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await policy_service.delete_policy(db, uuid.uuid4(), uuid.uuid4())
