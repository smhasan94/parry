"""The demo Okta tenant, run through the real discovery pipeline.

The fixture exists so the shadow-AI story can be shown without a live
Okta tenant. That only holds if it keeps producing the story — a catalog
rename or a matcher change could quietly turn the demo into an empty
table, and nobody would notice until it was on a screen in front of
someone. These tests pin the outcome, not just the parsing.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AISystem, Org, ProbeEvent, RiskClassification
from app.discovery.catalog_seed import seed_catalog
from app.discovery.okta import parse_okta_response
from app.discovery.sso_probe import SSOProbeProcessor
from app.services import discovery_service

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "okta_demo_tenant.json"


def _payload() -> list[dict]:
    return json.loads(FIXTURE.read_text())


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Demo Corp", clerk_org_id=f"demo_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _run(db: AsyncSession) -> Org:
    await seed_catalog(db)
    org = await _org(db)
    processor = await SSOProbeProcessor.create(db)
    await processor.process_events(db=db, org_id=org.id, events=parse_okta_response(_payload()))
    await db.flush()
    return org


def test_fixture_looks_like_a_real_okta_response() -> None:
    payload = _payload()

    assert len(payload) >= 15, "too small to look like a real tenant"
    for item in payload:
        assert set(item) == {"app", "users"}
        assert {"id", "label", "status", "created"} <= set(item["app"])
        assert item["app"]["id"].startswith("0oa")


def test_fixture_spreads_grants_across_many_users() -> None:
    payload = _payload()
    counts = sorted(len(i["users"]) for i in payload)

    # A tenant where every app has the same number of users reads as
    # synthetic the moment anyone looks at it.
    assert counts[0] <= 2, "no narrowly-adopted app — nothing looks like shadow IT"
    assert counts[-1] >= 20, "no broadly-adopted app — nothing looks sanctioned"
    assert len(set(counts)) >= 6, "user counts are too uniform to be believable"


@pytest.mark.asyncio
async def test_demo_surfaces_high_risk_hiring_tools_as_shadow_ai(db: AsyncSession):
    org = await _run(db)

    shadow = await discovery_service.list_shadow_systems(db, org_id=org.id)
    names = {s.name for s in shadow}

    # The point of the demo: Annex III employment screening running in the
    # environment that nothing is monitoring.
    assert "HireVue" in names
    assert "Eightfold AI" in names


@pytest.mark.asyncio
async def test_every_discovered_system_is_unmonitored(db: AsyncSession):
    org = await _run(db)

    shadow = await discovery_service.list_shadow_systems(db, org_id=org.id)

    assert shadow
    for system in shadow:
        assert system.origin == "discovered"
        assert system.agent_ids == []
        assert system.discovery_source == "sso"


@pytest.mark.asyncio
async def test_demo_surfaces_a_substantial_shadow_footprint(db: AsyncSession):
    org = await _run(db)

    summary = await discovery_service.shadow_summary(db, org_id=org.id)

    # Enough rows that the page reads as a real finding rather than a
    # toy. See the label-drift test below for why this is not 16.
    assert summary["total"] >= 10
    assert len(summary["by_risk_level"]) >= 1


@pytest.mark.asyncio
async def test_known_gap_okta_labels_that_drift_from_catalog_names_are_missed(
    db: AsyncSession,
):
    """Documents a real limitation, deliberately not papered over.

    SSOAppMatcher matches on exact OAuth client id or exact service name.
    Only 13 of 200 catalog entries carry an OAuth id, so in practice the
    name is the only lever — and admins rename apps. The fixture keeps
    realistic labels ("Figma", "Anthropic Claude") rather than tuning
    them to the catalog, so this gap shows up here instead of on a sales
    call.

    Fixing it means alias support on catalog entries, or normalized
    matching that tolerates an "AI"/vendor-prefix delta. Both risk false
    positives, which in a compliance register are worse than misses —
    hence a deliberate decision rather than a quick heuristic.

    When that lands, this test should start failing. That is the signal
    to delete it.
    """
    org = await _run(db)

    systems = (await db.execute(select(AISystem).where(AISystem.org_id == org.id))).scalars().all()
    names = {s.name for s in systems}

    # Present in the tenant under a drifted label, absent from the register.
    assert "Figma AI" not in names
    assert "Claude" not in names


@pytest.mark.asyncio
async def test_unrecognized_internal_apps_stay_out_of_the_register(db: AsyncSession):
    org = await _run(db)

    systems = (await db.execute(select(AISystem).where(AISystem.org_id == org.id))).scalars().all()
    probes = (
        (await db.execute(select(ProbeEvent).where(ProbeEvent.org_id == org.id))).scalars().all()
    )
    registered = {s.name for s in systems}

    # Present in the raw signal, absent from the compliance register.
    assert any("Payroll" in p.raw_payload["app"]["label"] for p in probes)
    assert not any("Payroll" in n for n in registered)


@pytest.mark.asyncio
async def test_catalog_tiers_arrive_pending_review_not_approved(db: AsyncSession):
    org = await _run(db)

    classifications = (
        (await db.execute(select(RiskClassification).where(RiskClassification.org_id == org.id)))
        .scalars()
        .all()
    )

    assert classifications
    assert {c.status for c in classifications} == {"pending_review"}
    assert {c.source for c in classifications} == {"catalog"}


@pytest.mark.asyncio
async def test_rerunning_the_demo_is_idempotent(db: AsyncSession):
    org = await _run(db)
    first = len(await discovery_service.list_shadow_systems(db, org_id=org.id))

    processor = await SSOProbeProcessor.create(db)
    result = await processor.process_events(
        db=db, org_id=org.id, events=parse_okta_response(_payload())
    )
    await db.flush()

    second = len(await discovery_service.list_shadow_systems(db, org_id=org.id))
    assert second == first
    assert result.created == 0
    assert result.deduplicated == result.processed
