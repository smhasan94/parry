"""Unit tests for agent_service.

DB calls are mocked. Covers list/get/create/update/delete: cursor
pagination, ConflictError on duplicate name, NotFoundError on missing
agent, the metadata→metadata_ key remap in update_agent, and the
soft-delete contract (delete_agent flips is_active rather than
removing the row).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Agent
from app.services import agent_service


def _make_agent(
    org_id: uuid.UUID,
    name: str = "test-agent",
    description: str | None = None,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        org_id=org_id,
        name=name,
        description=description,
        is_active=is_active,
        created_at=created_at or datetime.now(UTC),
    )


def _scalars_returning(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _execute_returning(row: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


# ── list_agents ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_agents_returns_empty_when_no_agents() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    agents, next_cursor = await agent_service.list_agents(db, uuid.uuid4())

    assert agents == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_agents_returns_rows_below_limit_without_cursor() -> None:
    org_id = uuid.uuid4()
    rows = [_make_agent(org_id, name=f"agent-{i}") for i in range(3)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    agents, next_cursor = await agent_service.list_agents(db, org_id, limit=10)

    assert len(agents) == 3
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_agents_returns_cursor_when_more_than_limit() -> None:
    org_id = uuid.uuid4()
    rows = [_make_agent(org_id, name=f"agent-{i}") for i in range(4)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    agents, next_cursor = await agent_service.list_agents(db, org_id, limit=3)

    assert len(agents) == 3
    assert next_cursor == str(agents[-1].id)


@pytest.mark.asyncio
async def test_list_agents_uses_cursor_to_filter_by_created_at() -> None:
    org_id = uuid.uuid4()
    cursor_agent = _make_agent(
        org_id, name="cursor", created_at=datetime.now(UTC) - timedelta(hours=1)
    )
    older = [
        _make_agent(
            org_id, name=f"older-{i}", created_at=datetime.now(UTC) - timedelta(hours=h)
        )
        for i, h in enumerate((2, 3))
    ]
    db = AsyncMock()
    db.get.return_value = cursor_agent
    db.execute.return_value = _scalars_returning(older)

    agents, _ = await agent_service.list_agents(
        db, org_id, cursor=str(cursor_agent.id), limit=10
    )

    assert len(agents) == 2
    db.get.assert_awaited_once()


# ── get_agent ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_agent_returns_agent_when_found() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    result = await agent_service.get_agent(db, org_id, agent.id)

    assert result is agent


@pytest.mark.asyncio
async def test_get_agent_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await agent_service.get_agent(db, uuid.uuid4(), uuid.uuid4())


# ── create_agent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_agent_persists_new_agent() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    # Duplicate-name lookup returns nothing
    db.execute.return_value = _execute_returning(None)

    result = await agent_service.create_agent(
        db, org_id, name="new-agent", description="desc"
    )

    assert result.name == "new-agent"
    assert result.description == "desc"
    assert result.org_id == org_id
    db.add.assert_called_once()
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_agent_raises_conflict_on_duplicate_name() -> None:
    org_id = uuid.uuid4()
    existing = _make_agent(org_id, name="taken")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(existing)

    with pytest.raises(ConflictError):
        await agent_service.create_agent(db, org_id, name="taken")

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_stores_metadata_under_metadata_attr() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    metadata = {"env": "prod", "team": "platform"}
    result = await agent_service.create_agent(
        db, org_id, name="new-agent", metadata=metadata
    )

    # The model attribute is metadata_ (mapped to "metadata" column)
    # because `metadata` is reserved on SQLAlchemy's DeclarativeBase.
    assert result.metadata_ == metadata


# ── update_agent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_agent_applies_simple_fields() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, description="old")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    result = await agent_service.update_agent(
        db, org_id, agent.id, description="new"
    )

    assert result.description == "new"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_agent_skips_none_values() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, description="keep me")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    result = await agent_service.update_agent(
        db, org_id, agent.id, description=None
    )

    assert result.description == "keep me"


@pytest.mark.asyncio
async def test_update_agent_remaps_metadata_key_to_metadata_attr() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    agent.metadata_ = {"old": "value"}
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    result = await agent_service.update_agent(
        db, org_id, agent.id, metadata={"new": "value"}
    )

    assert result.metadata_ == {"new": "value"}


@pytest.mark.asyncio
async def test_update_agent_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await agent_service.update_agent(
            db, uuid.uuid4(), uuid.uuid4(), description="x"
        )


# ── delete_agent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_agent_soft_deletes_by_marking_inactive() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, is_active=True)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    result = await agent_service.delete_agent(db, org_id, agent.id)

    # Soft-delete contract: row stays, is_active flips to False.
    assert result.is_active is False
    db.delete.assert_not_called()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_agent_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await agent_service.delete_agent(db, uuid.uuid4(), uuid.uuid4())
