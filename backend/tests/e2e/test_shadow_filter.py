"""What the shadow query includes and excludes, against a real database.

Replaces a mock that asserted the generated SQL mentioned 'origin' and
'agent_ids'. That passed whether or not the filter actually selected the
right rows, and broke the moment the query was rewritten.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AISystem, Org
from app.services import discovery_service


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Acme", clerk_org_id=f"f_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _system(db: AsyncSession, org: Org, *, name: str, **overrides) -> AISystem:
    defaults = {
        "org_id": org.id,
        "name": name,
        "origin": "discovered",
        "discovery_source": "sso",
        "risk_level": "unclassified",
        "status": "active",
        "agent_ids": [],
        "last_seen_at": datetime.now(UTC),
    }
    system = AISystem(**{**defaults, **overrides})
    db.add(system)
    await db.flush()
    return system


@pytest.mark.asyncio
async def test_includes_a_discovered_system_with_no_agents(db: AsyncSession):
    org = await _org(db)
    await _system(db, org, name="Shadow Tool")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert [r.name for r in rows] == ["Shadow Tool"]


@pytest.mark.asyncio
async def test_excludes_a_system_an_agent_already_covers(db: AsyncSession):
    org = await _org(db)
    await _system(db, org, name="Monitored", agent_ids=[uuid.uuid4()])

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    # Monitored is the entire point — it is not shadow AI any more.
    assert rows == []


@pytest.mark.asyncio
async def test_excludes_a_human_declared_system(db: AsyncSession):
    org = await _org(db)
    await _system(db, org, name="Declared", origin="declared")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    # Someone registered it deliberately. Nothing was hiding.
    assert rows == []


@pytest.mark.asyncio
async def test_excludes_a_retired_system(db: AsyncSession):
    org = await _org(db)
    await _system(db, org, name="Retired", status="retired")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert rows == []


@pytest.mark.asyncio
async def test_never_leaks_another_orgs_systems(db: AsyncSession):
    mine, theirs = await _org(db), await _org(db)
    await _system(db, theirs, name="Their Secret Tool")

    rows = await discovery_service.list_shadow_systems(db, org_id=mine.id)
    summary = await discovery_service.shadow_summary(db, org_id=mine.id)

    assert rows == []
    assert summary["total"] == 0


@pytest.mark.asyncio
async def test_orders_most_recently_seen_first(db: AsyncSession):
    org = await _org(db)
    await _system(db, org, name="Older", last_seen_at=datetime(2025, 1, 1, tzinfo=UTC))
    await _system(db, org, name="Newer", last_seen_at=datetime(2026, 6, 1, tzinfo=UTC))
    await _system(db, org, name="Never", last_seen_at=None)

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert [r.name for r in rows] == ["Newer", "Older", "Never"]


@pytest.mark.asyncio
async def test_limit_is_honoured(db: AsyncSession):
    org = await _org(db)
    for i in range(5):
        await _system(db, org, name=f"Tool {i}")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id, limit=3)

    assert len(rows) == 3
