"""Unit tests for discovery_service: probe hit -> register row."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.db.models import AICatalogEntry, AISystem, RiskClassification
from app.services import discovery_service


def _catalog_entry(
    *,
    service_name: str = "Notion AI",
    vendor: str = "Notion",
    default_risk_tier: str | None = "limited",
    rationale: str | None = "Generative assistant exposed to staff content.",
) -> AICatalogEntry:
    return AICatalogEntry(
        id=uuid.uuid4(),
        service_name=service_name,
        vendor=vendor,
        category="productivity",
        foundation_models=["gpt-4o"],
        oauth_app_ids=["0oa1notion"],
        default_risk_tier=default_risk_tier,
        risk_tier_rationale=rationale,
    )


def _db_finding(system: AISystem | None) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = system
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


async def test_reconcile_creates_a_discovered_system_when_none_exists() -> None:
    org_id = uuid.uuid4()
    entry = _catalog_entry()
    db = _db_finding(None)
    seen = datetime(2026, 3, 1, tzinfo=UTC)

    system = await discovery_service.reconcile_ai_system(
        db=db, org_id=org_id, catalog_entry=entry, discovery_source="sso", seen_at=seen
    )

    assert system.org_id == org_id
    assert system.name == "Notion AI"
    assert system.provider_name == "Notion"
    assert system.catalog_entry_id == entry.id
    assert system.origin == "discovered"
    assert system.discovery_source == "sso"
    assert system.first_seen_at == seen
    assert system.last_seen_at == seen


async def test_discovered_system_starts_unclassified_and_unmonitored() -> None:
    db = _db_finding(None)

    system = await discovery_service.reconcile_ai_system(
        db=db,
        org_id=uuid.uuid4(),
        catalog_entry=_catalog_entry(),
        discovery_source="sso",
        seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    # A probe cannot infer purpose or tier. Empty agent_ids is what makes
    # this row show up as shadow AI.
    assert system.risk_level == "unclassified"
    assert system.intended_purpose is None
    assert system.agent_ids == []


async def test_reconcile_seeds_a_pending_classification_from_the_catalog_tier() -> None:
    org_id = uuid.uuid4()
    entry = _catalog_entry(default_risk_tier="high", rationale="Screens job applicants.")
    db = _db_finding(None)

    await discovery_service.reconcile_ai_system(
        db=db,
        org_id=org_id,
        catalog_entry=entry,
        discovery_source="sso",
        seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    added = [c.args[0] for c in db.add.call_args_list]
    classifications = [o for o in added if isinstance(o, RiskClassification)]
    assert len(classifications) == 1
    assert classifications[0].risk_tier == "high"
    assert classifications[0].source == "catalog"
    assert classifications[0].status == "pending_review"
    assert classifications[0].reasoning == "Screens job applicants."
    assert classifications[0].org_id == org_id


async def test_no_classification_seeded_when_catalog_has_no_default_tier() -> None:
    db = _db_finding(None)

    await discovery_service.reconcile_ai_system(
        db=db,
        org_id=uuid.uuid4(),
        catalog_entry=_catalog_entry(default_risk_tier=None),
        discovery_source="sso",
        seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    added = [c.args[0] for c in db.add.call_args_list]
    assert not [o for o in added if isinstance(o, RiskClassification)]


async def test_reconcile_advances_last_seen_on_an_existing_system() -> None:
    entry = _catalog_entry()
    existing = AISystem(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="Notion AI",
        origin="discovered",
        catalog_entry_id=entry.id,
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        agent_ids=[],
    )
    db = _db_finding(existing)

    system = await discovery_service.reconcile_ai_system(
        db=db,
        org_id=existing.org_id,
        catalog_entry=entry,
        discovery_source="sso",
        seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    assert system is existing
    assert system.last_seen_at == datetime(2026, 3, 1, tzinfo=UTC)
    assert system.first_seen_at == datetime(2026, 1, 1, tzinfo=UTC)
    db.add.assert_not_called()


async def test_reconcile_never_rewinds_last_seen_for_a_late_arriving_event() -> None:
    entry = _catalog_entry()
    existing = AISystem(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="Notion AI",
        origin="discovered",
        catalog_entry_id=entry.id,
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen_at=datetime(2026, 3, 1, tzinfo=UTC),
        agent_ids=[],
    )
    db = _db_finding(existing)

    system = await discovery_service.reconcile_ai_system(
        db=db,
        org_id=existing.org_id,
        catalog_entry=entry,
        discovery_source="sso",
        seen_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert system.last_seen_at == datetime(2026, 3, 1, tzinfo=UTC)


async def test_reconcile_backfills_first_seen_when_a_declared_system_is_first_observed() -> None:
    # A human registered this system by hand; the probe is the first thing
    # to actually see it in the wild.
    entry = _catalog_entry()
    declared = AISystem(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="Notion AI",
        origin="declared",
        catalog_entry_id=entry.id,
        first_seen_at=None,
        last_seen_at=None,
        agent_ids=[],
    )
    db = _db_finding(declared)
    seen = datetime(2026, 3, 1, tzinfo=UTC)

    system = await discovery_service.reconcile_ai_system(
        db=db, org_id=declared.org_id, catalog_entry=entry, discovery_source="sso", seen_at=seen
    )

    assert system.first_seen_at == seen
    assert system.last_seen_at == seen
    # Human declaration outranks probe inference — do not downgrade it.
    assert system.origin == "declared"


# The shadow query itself is exercised against a real database in
# tests/e2e/test_shadow_filter.py — a mock that asserts on generated SQL
# only restates the implementation and breaks whenever the query is
# rewritten, without ever checking that the filter selects the right rows.


def test_effective_tier_prefers_an_approved_classification() -> None:
    row = discovery_service.ShadowSystem(
        id=uuid.uuid4(),
        name="HireVue",
        provider_name="HireVue, Inc.",
        risk_level="limited",
        proposed_risk_level="high",
        proposed_reasoning="catalog default",
        discovery_source="sso",
        first_seen_at=None,
        last_seen_at=None,
    )

    # A human decided 'limited'. The catalog's 'high' must not override it.
    assert row.effective_risk_level == "limited"
    assert row.is_proposed is False


def test_effective_tier_falls_back_to_the_pending_proposal() -> None:
    row = discovery_service.ShadowSystem(
        id=uuid.uuid4(),
        name="HireVue",
        provider_name="HireVue, Inc.",
        risk_level="unclassified",
        proposed_risk_level="high",
        proposed_reasoning="Annex III employment screening",
        discovery_source="sso",
        first_seen_at=None,
        last_seen_at=None,
    )

    assert row.effective_risk_level == "high"
    assert row.is_proposed is True


def test_effective_tier_is_unclassified_when_nothing_is_known() -> None:
    row = discovery_service.ShadowSystem(
        id=uuid.uuid4(),
        name="Mystery Tool",
        provider_name=None,
        risk_level="unclassified",
        proposed_risk_level=None,
        proposed_reasoning=None,
        discovery_source="sso",
        first_seen_at=None,
        last_seen_at=None,
    )

    assert row.effective_risk_level == "unclassified"
    assert row.is_proposed is False
