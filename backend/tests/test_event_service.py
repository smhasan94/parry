"""Unit tests for event_service.

DB calls are mocked. The intricate logic in ingest_event is the
session resolution branch tree (no session_id / valid UUID hitting an
existing same-agent session / valid UUID hitting an existing
*different-agent* session / valid UUID with no existing row /
non-UUID string), plus the agent auto-create branch and the 80/20
input/output cost split. list/get are simpler — pagination + the
event-id-only fetch branch (AgentEvent is a hypertable so db.get is
not used).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.db.models import Agent, AgentEvent, AgentSession
from app.services import event_service


def _make_agent(org_id: uuid.UUID, name: str = "test-agent") -> Agent:
    return Agent(
        id=uuid.uuid4(),
        org_id=org_id,
        name=name,
        is_active=True,
    )


def _make_event(
    agent_id: uuid.UUID,
    timestamp: datetime | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=uuid.uuid4(),
        agent_id=agent_id,
        timestamp=timestamp or datetime.now(UTC),
        prompt="hello",
        response="hi",
    )


def _execute_returning(row: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _scalars_returning(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


# ── ingest_event: agent resolution ────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_event_auto_creates_agent_when_missing() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    # First execute (agent lookup) → None, triggers auto-create.
    db.execute.return_value = _execute_returning(None)

    event = await event_service.ingest_event(
        db, org_id, agent_name="brand-new", model="gpt-4o", token_count=100
    )

    # Two add() calls: the new Agent + the AgentEvent.
    assert db.add.call_count == 2
    # The first add is the agent.
    new_agent = db.add.call_args_list[0].args[0]
    assert isinstance(new_agent, Agent)
    assert new_agent.name == "brand-new"
    assert new_agent.org_id == org_id
    # Returned event references the new agent's id.
    assert event.agent_id == new_agent.id


@pytest.mark.asyncio
async def test_ingest_event_reuses_existing_agent() -> None:
    org_id = uuid.uuid4()
    existing = _make_agent(org_id, name="existing")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(existing)

    event = await event_service.ingest_event(
        db, org_id, agent_name="existing", model="gpt-4o", token_count=50
    )

    # Only one add — the AgentEvent. No new Agent row.
    assert db.add.call_count == 1
    added = db.add.call_args_list[0].args[0]
    assert isinstance(added, AgentEvent)
    assert event.agent_id == existing.id


# ── ingest_event: session resolution ──────────────────────────────


@pytest.mark.asyncio
async def test_ingest_event_with_no_session_id_does_not_create_session() -> None:
    org_id = uuid.uuid4()
    existing = _make_agent(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(existing)

    event = await event_service.ingest_event(
        db, org_id, agent_name="test-agent", session_id=None
    )

    assert event.session_id is None
    # Just the event got added.
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_ingest_event_with_uuid_session_id_reuses_existing_session() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    existing_session = AgentSession(id=uuid.uuid4(), agent_id=agent.id)

    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)
    db.get.return_value = existing_session

    event = await event_service.ingest_event(
        db,
        org_id,
        agent_name="test-agent",
        session_id=str(existing_session.id),
    )

    assert event.session_id == existing_session.id
    # Only the event got added — the session already existed.
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_ingest_event_rejects_session_id_belonging_to_different_agent() -> None:
    """Cross-agent guard: if the session_id maps to another agent's
    session, defence-in-depth creates a fresh AgentSession bound to
    *this* agent. (The new row reuses the client-provided UUID so the
    deterministic-key contract still holds for this agent — the
    important property is that the resulting session row's
    ``agent_id`` belongs to the caller, not the original owner.)"""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    other_owner_id = uuid.uuid4()
    other_agent_session = AgentSession(id=uuid.uuid4(), agent_id=other_owner_id)

    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)
    db.get.return_value = other_agent_session

    event = await event_service.ingest_event(
        db,
        org_id,
        agent_name="test-agent",
        session_id=str(other_agent_session.id),
    )

    # Two adds: a brand-new AgentSession row + the AgentEvent.
    assert db.add.call_count == 2
    new_session = db.add.call_args_list[0].args[0]
    assert isinstance(new_session, AgentSession)
    # New row is bound to THIS agent, not the original owner.
    assert new_session.agent_id == agent.id
    assert new_session.agent_id != other_owner_id
    # The event references the new (correctly-bound) session.
    assert event.session_id == new_session.id


@pytest.mark.asyncio
async def test_ingest_event_with_uuid_session_id_creates_when_missing() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    new_id = uuid.uuid4()

    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)
    db.get.return_value = None  # No existing session for that UUID

    event = await event_service.ingest_event(
        db, org_id, agent_name="test-agent", session_id=str(new_id)
    )

    # Service preserves the client-provided UUID as the session id.
    assert event.session_id == new_id
    new_session = db.add.call_args_list[0].args[0]
    assert isinstance(new_session, AgentSession)
    assert new_session.id == new_id
    assert new_session.agent_id == agent.id


@pytest.mark.asyncio
async def test_ingest_event_with_non_uuid_session_id_creates_fresh_session() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)

    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    event = await event_service.ingest_event(
        db, org_id, agent_name="test-agent", session_id="thread_abc_123"
    )

    # A non-UUID hint never collides with db.get.
    db.get.assert_not_called()
    # New session row added with auto-generated UUID.
    assert event.session_id is not None
    new_session = db.add.call_args_list[0].args[0]
    assert isinstance(new_session, AgentSession)
    assert new_session.metadata_ == {"client_session_id": "thread_abc_123"}


# ── ingest_event: cost computation ────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_event_estimates_cost_from_known_model() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    fake_cost = 0.0042
    with patch.object(
        event_service, "estimate_cost", return_value=fake_cost
    ) as mock_estimate:
        event = await event_service.ingest_event(
            db, org_id, agent_name="test-agent", model="gpt-4o", token_count=1000
        )

    assert event.estimated_cost_usd == fake_cost
    # 80/20 split: 1000 → 800 input / 200 output.
    mock_estimate.assert_called_once_with("gpt-4o", 800, 200)


@pytest.mark.asyncio
async def test_ingest_event_with_no_token_count_estimates_zero_cost() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    event = await event_service.ingest_event(
        db, org_id, agent_name="test-agent", model="gpt-4o", token_count=None
    )

    # 0 input / 0 output → unknown-model fallback path returns 0 too.
    assert event.estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_ingest_event_propagates_explicit_timestamp() -> None:
    org_id = uuid.uuid4()
    agent = _make_agent(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(agent)

    fixed = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    event = await event_service.ingest_event(
        db, org_id, agent_name="test-agent", timestamp=fixed
    )

    assert event.timestamp == fixed


# ── list_events ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_events_returns_empty_when_no_events() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    events, next_cursor = await event_service.list_events(db, uuid.uuid4())

    assert events == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_events_returns_cursor_when_more_than_limit() -> None:
    agent_id = uuid.uuid4()
    rows = [_make_event(agent_id) for _ in range(4)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    events, next_cursor = await event_service.list_events(db, agent_id, limit=3)

    assert len(events) == 3
    assert next_cursor == str(events[-1].id)


@pytest.mark.asyncio
async def test_list_events_uses_cursor_event_timestamp_for_pagination() -> None:
    agent_id = uuid.uuid4()
    cursor_ev = _make_event(agent_id, timestamp=datetime.now(UTC) - timedelta(hours=1))
    older = [
        _make_event(agent_id, timestamp=datetime.now(UTC) - timedelta(hours=h))
        for h in (2, 3)
    ]
    db = AsyncMock()
    # First execute resolves the cursor event by id (hypertable can't use db.get).
    # Second execute returns the older page.
    db.execute.side_effect = [
        _execute_returning(cursor_ev),
        _scalars_returning(older),
    ]

    events, _ = await event_service.list_events(
        db, agent_id, cursor=str(cursor_ev.id), limit=10
    )

    assert len(events) == 2
    db.get.assert_not_called()  # Hypertable path, not db.get.


# ── get_event ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_event_returns_event_when_found() -> None:
    event = _make_event(uuid.uuid4())
    db = AsyncMock()
    db.execute.return_value = _execute_returning(event)

    result = await event_service.get_event(db, event.id)

    assert result is event


@pytest.mark.asyncio
async def test_get_event_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await event_service.get_event(db, uuid.uuid4())
