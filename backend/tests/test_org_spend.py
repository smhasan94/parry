"""Tests for the org-wide spend summary endpoint logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.spend import org_spend_summary


def _make_org(org_id: uuid.UUID | None = None) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    return org


# ── helpers ────────────────────────────────────────────────────────────────


def _make_db(
    agent_rows: list[tuple[uuid.UUID, str]],
    period_spend: tuple[float, float, float] = (0.5, 2.0, 15.0),
    per_agent_rows: list[tuple[uuid.UUID, float]] | None = None,
    budget_cap: float | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession that returns predictable query results.

    Query call order matches the implementation:
      0 – agent id/name list
      1 – hour spend sum
      2 – day spend sum
      3 – month spend sum
      4 – per-agent breakdown
      5 – org budget cap
    """
    db = AsyncMock()

    def _scalar_result(value: object) -> MagicMock:
        r = MagicMock()
        r.scalar_one.return_value = value
        r.scalar_one_or_none.return_value = value
        r.all.return_value = []
        return r

    def _all_result(rows: list) -> MagicMock:
        r = MagicMock()
        r.all.return_value = rows
        return r

    if per_agent_rows is None:
        per_agent_rows = [(aid, 10.0) for aid, _ in agent_rows[:1]] if agent_rows else []

    # Build rows for per-agent query
    per_agent_mock_rows = []
    for aid, total in per_agent_rows:
        row = MagicMock()
        row.agent_id = aid
        row.total = total
        per_agent_mock_rows.append(row)

    # Each call to db.execute returns a different mock based on call order.
    execute_results = [
        _all_result(agent_rows),          # 0 – agents
        _scalar_result(period_spend[0]),   # 1 – hour
        _scalar_result(period_spend[1]),   # 2 – day
        _scalar_result(period_spend[2]),   # 3 – month
        _all_result(per_agent_mock_rows),  # 4 – per-agent
        _scalar_result(budget_cap),        # 5 – org budget
    ]

    db.execute = AsyncMock(side_effect=execute_results)
    return db


# ── tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_spend_summary_basic() -> None:
    """Returns correct aggregated spend across all three periods."""
    agent_id = uuid.uuid4()
    org = _make_org()
    db = _make_db(
        agent_rows=[(agent_id, "my-agent")],
        period_spend=(0.05, 1.20, 30.50),
        per_agent_rows=[(agent_id, 30.50)],
        budget_cap=None,
    )

    result = await org_spend_summary(org=org, db=db)

    assert result.hour_spend == pytest.approx(0.05)
    assert result.day_spend == pytest.approx(1.20)
    assert result.month_spend == pytest.approx(30.50)
    assert result.total_budget_cap is None


@pytest.mark.asyncio
async def test_org_spend_summary_no_agents() -> None:
    """Returns zeros and empty list when the org has no agents."""
    org = _make_org()
    db = AsyncMock()

    # Only the agent query fires; everything else is short-circuited.
    agent_result = MagicMock()
    agent_result.all.return_value = []
    db.execute = AsyncMock(return_value=agent_result)

    result = await org_spend_summary(org=org, db=db)

    assert result.hour_spend == 0.0
    assert result.day_spend == 0.0
    assert result.month_spend == 0.0
    assert result.top_agents == []
    assert result.total_budget_cap is None
    # Only one execute call (the agents query); no further DB work.
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_org_spend_summary_with_budget_cap() -> None:
    """total_budget_cap is populated when an org-wide monthly budget exists."""
    agent_id = uuid.uuid4()
    org = _make_org()
    db = _make_db(
        agent_rows=[(agent_id, "bot")],
        period_spend=(0.0, 0.0, 50.0),
        per_agent_rows=[(agent_id, 50.0)],
        budget_cap=200.0,
    )

    result = await org_spend_summary(org=org, db=db)

    assert result.total_budget_cap == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_org_spend_summary_top_agents() -> None:
    """top_agents list is populated with per-agent spend entries."""
    agent_id_1 = uuid.uuid4()
    agent_id_2 = uuid.uuid4()
    org = _make_org()
    db = _make_db(
        agent_rows=[(agent_id_1, "agent-a"), (agent_id_2, "agent-b")],
        period_spend=(0.1, 1.0, 80.0),
        per_agent_rows=[(agent_id_1, 60.0), (agent_id_2, 20.0)],
        budget_cap=None,
    )

    result = await org_spend_summary(org=org, db=db)

    assert len(result.top_agents) == 2
    assert result.top_agents[0].agent_id == agent_id_1
    assert result.top_agents[0].agent_name == "agent-a"
    assert result.top_agents[0].month_spend == pytest.approx(60.0)
    assert result.top_agents[1].agent_id == agent_id_2
    assert result.top_agents[1].month_spend == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_org_spend_summary_zero_spend() -> None:
    """All periods return 0.0 when there are no events."""
    agent_id = uuid.uuid4()
    org = _make_org()
    db = _make_db(
        agent_rows=[(agent_id, "idle-agent")],
        period_spend=(0.0, 0.0, 0.0),
        per_agent_rows=[],
        budget_cap=None,
    )

    result = await org_spend_summary(org=org, db=db)

    assert result.hour_spend == 0.0
    assert result.day_spend == 0.0
    assert result.month_spend == 0.0
    assert result.top_agents == []
