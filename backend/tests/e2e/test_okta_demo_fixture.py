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
    assert {s.discovery_source for s in shadow} == {"sso"}

    # origin and agent_ids are register invariants rather than display
    # fields, so check them on the rows themselves.
    listed = {s.id for s in shadow}
    systems = (await db.execute(select(AISystem).where(AISystem.id.in_(listed)))).scalars().all()
    assert len(systems) == len(listed)
    for system in systems:
        assert system.origin == "discovered"
        assert system.agent_ids == []


@pytest.mark.asyncio
async def test_demo_flags_high_risk_hiring_tools_without_a_human_review(db: AsyncSession):
    org = await _run(db)

    shadow = await discovery_service.list_shadow_systems(db, org_id=org.id)
    high = {s.name for s in shadow if s.effective_risk_level == "high"}

    # The demo's opening line: Annex III employment screening, flagged
    # from the catalog, awaiting review, monitored by nothing.
    assert {"HireVue", "Eightfold AI"} <= high
    for row in shadow:
        if row.name in high:
            assert row.is_proposed is True
            assert row.risk_level == "unclassified"


@pytest.mark.asyncio
async def test_demo_surfaces_a_substantial_shadow_footprint(db: AsyncSession):
    org = await _run(db)

    summary = await discovery_service.shadow_summary(db, org_id=org.id)

    # Enough rows that the page reads as a real finding rather than a
    # toy. See the label-drift test below for why this is not 16.
    assert summary["total"] >= 10
    assert len(summary["by_risk_level"]) >= 1


@pytest.mark.asyncio
async def test_renamed_apps_are_now_matched(db: AsyncSession):
    """Labels that drift from the catalog name are recovered.

    Replaces a test that documented these as a known gap. The fixture
    still carries realistic Okta labels rather than ones tuned to match,
    so this is evidence against real-shaped data.
    """
    org = await _run(db)

    systems = (await db.execute(select(AISystem).where(AISystem.org_id == org.id))).scalars().all()
    names = {s.name for s in systems}

    # "OpenAI ChatGPT Enterprise", "Anthropic Claude", "Perplexity AI"
    # in the tenant; "ChatGPT", "Claude", "Perplexity" in the catalog.
    assert {"ChatGPT", "Claude", "Perplexity"} <= names


@pytest.mark.asyncio
async def test_a_bare_vendor_grant_still_does_not_claim_its_ai_product(
    db: AsyncSession,
):
    """The half of the gap that stays closed on purpose.

    The tenant grants "Figma", "Intercom" and "Greenhouse". The catalog
    calls the corresponding AI products "Figma AI", "Intercom Fin" and
    "Greenhouse AI". Matching those would assert the org uses each
    vendor's AI features on the evidence of a grant that says only that
    they use the vendor — and the assertion would land in a compliance
    register, where a wrong row is worse than a missing one.

    They remain probe events for a human to triage.
    """
    org = await _run(db)

    systems = (await db.execute(select(AISystem).where(AISystem.org_id == org.id))).scalars().all()
    names = {s.name for s in systems}

    assert "Figma AI" not in names
    assert "Intercom Fin" not in names
    assert "Greenhouse AI" not in names


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
