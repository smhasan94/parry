"""Review of proposed risk classifications.

Discovery seeds a tier from the vendor catalog as a *proposal*. This is
where a human turns one into the system's tier of record — the value that
drives the Article 26 register and, for high-risk Annex III deployments,
the Article 27 FRIA obligation.

Approval is deliberately the only path that writes ``ai_systems.risk_level``
from a catalog suggestion. Nothing here infers a tier; it only ratifies one
a person chose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import RiskClassification
from app.services import ai_system_service, audit_service

log = structlog.get_logger()

_UNDECIDED = "pending_review"


async def list_pending(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 100,
) -> list[RiskClassification]:
    """The review queue: proposals nobody has ruled on yet."""
    result = await db.execute(
        select(RiskClassification)
        .where(
            RiskClassification.org_id == org_id,
            RiskClassification.status == _UNDECIDED,
        )
        .order_by(RiskClassification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _undecided(
    db: AsyncSession, org_id: uuid.UUID, classification_id: uuid.UUID
) -> RiskClassification:
    result = await db.execute(
        select(RiskClassification).where(
            RiskClassification.id == classification_id,
            RiskClassification.org_id == org_id,
        )
    )
    classification = result.scalar_one_or_none()
    if classification is None:
        # Same response whether it belongs to another org or does not
        # exist — an id should not be probeable across tenants.
        raise NotFoundError("RiskClassification", str(classification_id))
    if classification.status != _UNDECIDED:
        raise ConflictError(
            f"classification {classification_id} was already {classification.status}"
        )
    return classification


async def approve(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    classification_id: uuid.UUID,
    reviewed_by: str,
) -> RiskClassification:
    """Ratify a proposed tier and make it the system's tier of record.

    Routes the write through ``ai_system_service.update_system`` so the
    FRIA obligation is derived in exactly one place rather than being
    re-implemented here and drifting from it.
    """
    classification = await _undecided(db, org_id, classification_id)

    classification.status = "approved"
    classification.reviewed_by = reviewed_by
    classification.reviewed_at = datetime.now(tz=UTC)

    await ai_system_service.update_system(
        db, org_id, classification.system_id, risk_level=classification.risk_tier
    )
    superseded = await _supersede_other_pending(db, classification)

    await audit_service.log_action(
        db,
        org_id,
        "classification.approved",
        actor_type="user",
        actor_id=reviewed_by,
        resource_type="risk_classification",
        resource_id=str(classification.id),
        details={
            "system_id": str(classification.system_id),
            "risk_tier": classification.risk_tier,
            "source": classification.source,
            "superseded": superseded,
        },
        obligation_ids=["art_26_1_deployer_register"],
    )

    await db.flush()
    log.info(
        "classification.approved",
        org_id=str(org_id),
        classification_id=str(classification.id),
        risk_tier=classification.risk_tier,
    )
    return classification


async def reject(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    classification_id: uuid.UUID,
    reviewed_by: str,
    reason: str | None = None,
) -> RiskClassification:
    """Decline a proposed tier.

    The system keeps whatever tier it already had — a rejected proposal
    must never become the tier of record by omission.
    """
    classification = await _undecided(db, org_id, classification_id)

    classification.status = "rejected"
    classification.reviewed_by = reviewed_by
    classification.reviewed_at = datetime.now(tz=UTC)

    await audit_service.log_action(
        db,
        org_id,
        "classification.rejected",
        actor_type="user",
        actor_id=reviewed_by,
        resource_type="risk_classification",
        resource_id=str(classification.id),
        details={
            "system_id": str(classification.system_id),
            "risk_tier": classification.risk_tier,
            "reason": reason,
        },
        obligation_ids=["art_26_1_deployer_register"],
    )

    await db.flush()
    log.info(
        "classification.rejected",
        org_id=str(org_id),
        classification_id=str(classification.id),
    )
    return classification


async def _supersede_other_pending(db: AsyncSession, approved: RiskClassification) -> int:
    """Close out competing proposals for the same system.

    Leaving them pending would keep re-proposing a tier the reviewer has
    effectively already passed over, and the shadow list would keep
    showing a proposal for a system that now has an approved tier.
    """
    result = await db.execute(
        select(RiskClassification).where(
            RiskClassification.system_id == approved.system_id,
            RiskClassification.status == _UNDECIDED,
            RiskClassification.id != approved.id,
        )
    )
    others = list(result.scalars().all())
    for other in others:
        other.status = "rejected"
        other.reviewed_by = approved.reviewed_by
        other.reviewed_at = approved.reviewed_at
    return len(others)
