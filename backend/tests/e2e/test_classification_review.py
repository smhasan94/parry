"""Approving or rejecting a proposed risk tier.

Discovery seeds a pending classification from the vendor catalog, and the
shadow page labels it "pending review" — but until now nothing could
review it. This closes that loop: an approved tier becomes the system's
tier of record, which is what drives the Article 26 register and the
Article 27 FRIA obligation downstream.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import AISystem, AuditLog, Org, RiskClassification
from app.services import classification_service


async def _org(db: AsyncSession) -> Org:
    org = Org(name="Acme", clerk_org_id=f"r_{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _system(db: AsyncSession, org: Org, *, name: str = "HireVue") -> AISystem:
    system = AISystem(
        org_id=org.id,
        name=name,
        origin="discovered",
        discovery_source="sso",
        risk_level="unclassified",
        status="active",
        agent_ids=[],
        last_seen_at=datetime.now(UTC),
    )
    db.add(system)
    await db.flush()
    return system


async def _pending(
    db: AsyncSession, org: Org, system: AISystem, *, tier: str = "high"
) -> RiskClassification:
    rc = RiskClassification(
        org_id=org.id,
        system_id=system.id,
        source="catalog",
        risk_tier=tier,
        reasoning="Screens job applicants — Annex III employment.",
        status="pending_review",
    )
    db.add(rc)
    await db.flush()
    return rc


@pytest.mark.asyncio
async def test_approving_records_who_decided_and_when(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system)

    approved = await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )

    assert approved.status == "approved"
    assert approved.reviewed_by == "user_ada"
    assert approved.reviewed_at is not None


@pytest.mark.asyncio
async def test_approving_promotes_the_tier_onto_the_system(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system, tier="high")

    await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )
    await db.refresh(system)

    # The system's tier of record — no longer a proposal.
    assert system.risk_level == "high"


@pytest.mark.asyncio
async def test_approving_high_risk_raises_the_fria_obligation(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system, tier="high")

    await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )
    await db.refresh(system)

    # Article 27: a high-risk Annex III deployment owes a FRIA. This is
    # the join that makes discovery feed the compliance product.
    assert system.fria_required is True
    assert system.fria_status == "missing"


@pytest.mark.asyncio
async def test_approving_a_lower_tier_raises_no_fria_obligation(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system, tier="limited")

    await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )
    await db.refresh(system)

    assert system.risk_level == "limited"
    assert system.fria_required is False
    assert system.fria_status == "not_required"


@pytest.mark.asyncio
async def test_rejecting_leaves_the_system_unclassified(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system, tier="high")

    rejected = await classification_service.reject(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )
    await db.refresh(system)

    assert rejected.status == "rejected"
    # A rejected proposal must not silently become the tier of record.
    assert system.risk_level == "unclassified"
    assert system.fria_required is False


@pytest.mark.asyncio
async def test_approving_supersedes_other_pending_proposals(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    stale = await _pending(db, org, system, tier="minimal")
    chosen = await _pending(db, org, system, tier="high")

    await classification_service.approve(
        db, org_id=org.id, classification_id=chosen.id, reviewed_by="user_ada"
    )
    await db.refresh(stale)

    # Leaving them pending would keep re-proposing a tier the reviewer
    # has effectively already passed over.
    assert stale.status == "rejected"


@pytest.mark.asyncio
async def test_a_decided_classification_cannot_be_decided_again(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system)
    await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )

    with pytest.raises(ConflictError):
        await classification_service.approve(
            db, org_id=org.id, classification_id=rc.id, reviewed_by="user_grace"
        )


@pytest.mark.asyncio
async def test_another_orgs_classification_is_not_reviewable(db: AsyncSession):
    mine, theirs = await _org(db), await _org(db)
    system = await _system(db, theirs)
    rc = await _pending(db, theirs, system)

    with pytest.raises(NotFoundError):
        await classification_service.approve(
            db, org_id=mine.id, classification_id=rc.id, reviewed_by="user_ada"
        )


@pytest.mark.asyncio
async def test_a_decision_is_written_to_the_audit_log(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    rc = await _pending(db, org, system, tier="high")

    await classification_service.approve(
        db, org_id=org.id, classification_id=rc.id, reviewed_by="user_ada"
    )

    entries = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.org_id == org.id,
                    AuditLog.action == "classification.approved",
                )
            )
        )
        .scalars()
        .all()
    )

    # Who set an Annex III tier, and to what, is the question an auditor
    # asks first.
    assert len(entries) == 1
    assert entries[0].resource_id == str(rc.id)
    assert entries[0].details["risk_tier"] == "high"
    assert entries[0].details["system_id"] == str(system.id)


@pytest.mark.asyncio
async def test_pending_queue_lists_only_undecided_proposals(db: AsyncSession):
    org = await _org(db)
    system = await _system(db, org)
    keep = await _pending(db, org, system, tier="high")
    decided = await _pending(db, org, system, tier="minimal")
    await classification_service.reject(
        db, org_id=org.id, classification_id=decided.id, reviewed_by="user_ada"
    )

    queue = await classification_service.list_pending(db, org_id=org.id)

    assert [c.id for c in queue] == [keep.id]


@pytest.mark.asyncio
async def test_pending_queue_is_scoped_to_the_org(db: AsyncSession):
    mine, theirs = await _org(db), await _org(db)
    system = await _system(db, theirs)
    await _pending(db, theirs, system)

    assert await classification_service.list_pending(db, org_id=mine.id) == []
