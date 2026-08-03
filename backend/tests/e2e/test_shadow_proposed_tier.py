"""The shadow list must show the tier the catalog already proposed.

Discovered systems sit at risk_level='unclassified' until a human
approves a classification, which is correct for the register but made the
shadow page render every row as "unclassified" — hiding the fact that the
catalog had already flagged three of them as Annex III high risk. The
information existed; the query just wasn't asking for it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry, AISystem, Org, RiskClassification
from app.services import discovery_service


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Acme", clerk_org_id=f"t_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _entry(db: AsyncSession, name: str = "HireVue") -> AICatalogEntry:
    entry = AICatalogEntry(
        service_name=f"{name}-{uuid.uuid4().hex[:6]}",
        vendor=name,
        category="hiring",
        default_risk_tier="high",
    )
    db.add(entry)
    await db.flush()
    return entry


async def _system(
    db: AsyncSession, org: Org, *, name: str = "HireVue", risk_level: str = "unclassified"
) -> AISystem:
    entry = await _entry(db, name)
    system = AISystem(
        org_id=org.id,
        name=name,
        provider_name=name,
        catalog_entry_id=entry.id,
        origin="discovered",
        discovery_source="sso",
        risk_level=risk_level,
        status="active",
        agent_ids=[],
        last_seen_at=datetime.now(UTC),
    )
    db.add(system)
    await db.flush()
    return system


async def _classify(
    db: AsyncSession,
    org: Org,
    system: AISystem,
    *,
    tier: str = "high",
    status: str = "pending_review",
    reasoning: str = "Screens job applicants — Annex III employment.",
    created_at: datetime | None = None,
) -> RiskClassification:
    rc = RiskClassification(
        org_id=org.id,
        system_id=system.id,
        source="catalog",
        risk_tier=tier,
        reasoning=reasoning,
        status=status,
    )
    if created_at is not None:
        rc.created_at = created_at
    db.add(rc)
    await db.flush()
    return rc


@pytest.mark.asyncio
async def test_pending_catalog_tier_is_surfaced_as_a_proposal(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    await _classify(db, org, system)

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert len(rows) == 1
    assert rows[0].risk_level == "unclassified"
    assert rows[0].proposed_risk_level == "high"
    assert "Annex III" in rows[0].proposed_reasoning


@pytest.mark.asyncio
async def test_effective_tier_falls_back_to_the_proposal(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    await _classify(db, org, system, tier="high")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    # What the page should render.
    assert rows[0].effective_risk_level == "high"
    assert rows[0].is_proposed is True


@pytest.mark.asyncio
async def test_an_approved_tier_outranks_a_pending_proposal(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org, risk_level="limited")
    await _classify(db, org, system, tier="high")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    # A human decided. A catalog default must never override that.
    assert rows[0].effective_risk_level == "limited"
    assert rows[0].is_proposed is False


@pytest.mark.asyncio
async def test_system_with_no_classification_has_no_proposal(db: AsyncSession):
    org = await _org(db)
    await _system(db, org)

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert rows[0].proposed_risk_level is None
    assert rows[0].effective_risk_level == "unclassified"
    assert rows[0].is_proposed is False


@pytest.mark.asyncio
async def test_rejected_classifications_are_not_proposed(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    await _classify(db, org, system, tier="high", status="rejected")

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    # Someone looked at this and said no. Do not keep suggesting it.
    assert rows[0].proposed_risk_level is None


@pytest.mark.asyncio
async def test_the_most_recent_pending_classification_wins(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    now = datetime.now(UTC)
    await _classify(db, org, system, tier="minimal", created_at=now - timedelta(days=2))
    await _classify(db, org, system, tier="high", created_at=now)

    rows = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert rows[0].proposed_risk_level == "high"


@pytest.mark.asyncio
async def test_summary_groups_by_effective_tier_not_raw_risk_level(db: AsyncSession):
    org = await _org(db)
    for name, tier in [("HireVue", "high"), ("Eightfold", "high"), ("Notion", "minimal")]:
        system = await _system(db, org, name=name)
        await _classify(db, org, system, tier=tier)

    summary = await discovery_service.shadow_summary(db, org_id=org.id)

    # Previously every one of these landed in a single 'unclassified'
    # bucket, which told the viewer nothing.
    assert summary["total"] == 3
    assert summary["by_risk_level"] == {"high": 2, "minimal": 1}
