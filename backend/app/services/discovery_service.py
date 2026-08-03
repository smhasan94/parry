"""Turn probe hits into rows in the AI system register.

A probe tells you a vendor is in use. This module decides whether that
means a new register entry or a fresher timestamp on an existing one, and
seeds the catalog's default risk tier as a *pending* classification —
never an approved one. A machine-proposed Annex III tier is a draft for a
human to approve, not a compliance fact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry, AISystem, RiskClassification
from app.services import audit_service

log = structlog.get_logger()


async def reconcile_ai_system(
    *,
    db: AsyncSession,
    org_id: uuid.UUID,
    catalog_entry: AICatalogEntry,
    discovery_source: str,
    seen_at: datetime,
) -> AISystem:
    """Upsert the register row for a discovered vendor.

    Idempotent per (org, catalog entry) — re-running a sync advances
    ``last_seen_at`` and nothing else.
    """
    result = await db.execute(
        select(AISystem).where(
            AISystem.org_id == org_id,
            AISystem.catalog_entry_id == catalog_entry.id,
        )
    )
    system = result.scalar_one_or_none()

    if system is not None:
        # Monotonic: probes can deliver out of order, and a late batch
        # must not make a system look staler than it is.
        if system.last_seen_at is None or seen_at > system.last_seen_at:
            system.last_seen_at = seen_at
        if system.first_seen_at is None:
            system.first_seen_at = seen_at
        await db.flush()
        return system

    system = AISystem(
        org_id=org_id,
        name=catalog_entry.service_name,
        provider_name=catalog_entry.vendor,
        catalog_entry_id=catalog_entry.id,
        origin="discovered",
        discovery_source=discovery_source,
        risk_level="unclassified",
        status="active",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        agent_ids=[],
    )
    db.add(system)
    await db.flush()

    if catalog_entry.default_risk_tier:
        db.add(
            RiskClassification(
                org_id=org_id,
                system_id=system.id,
                source="catalog",
                risk_tier=catalog_entry.default_risk_tier,
                reasoning=catalog_entry.risk_tier_rationale or "Default tier from the AI catalog.",
                status="pending_review",
            )
        )

    await audit_service.log_action(
        db,
        org_id,
        "ai_system.discovered",
        resource_type="ai_system",
        resource_id=str(system.id),
        details={
            "name": system.name,
            "vendor": catalog_entry.vendor,
            "discovery_source": discovery_source,
            "catalog_entry_id": str(catalog_entry.id),
        },
        obligation_ids=["art_26_1_deployer_register"],
    )

    log.info(
        "ai_system_discovered",
        org_id=str(org_id),
        system_id=str(system.id),
        vendor=catalog_entry.vendor,
        source=discovery_source,
    )
    return system


@dataclass(frozen=True)
class ShadowSystem:
    """A discovered, unmonitored system plus the tier the catalog proposed.

    ``risk_level`` is what a human approved; ``proposed_risk_level`` is
    what the catalog suggested and nobody has ruled on yet. Keeping them
    apart matters — the register must never present a machine's guess as
    an approved Annex III classification — but hiding the proposal made
    every discovered system render as "unclassified" when the catalog had
    already flagged some of them as high risk.
    """

    id: uuid.UUID
    name: str
    provider_name: str | None
    risk_level: str
    proposed_risk_level: str | None
    proposed_reasoning: str | None
    discovery_source: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None

    @property
    def effective_risk_level(self) -> str:
        """The tier to display: an approved one if it exists, else the
        proposal, else nothing known."""
        if self.risk_level != "unclassified":
            return self.risk_level
        return self.proposed_risk_level or "unclassified"

    @property
    def is_proposed(self) -> bool:
        """True when the displayed tier is awaiting human review."""
        return self.risk_level == "unclassified" and self.proposed_risk_level is not None


def _latest_pending(column: Any) -> Any:
    """Correlated lookup of the newest pending classification for a system.

    Rejected and approved rows are excluded: a rejected proposal is one a
    human already declined, and re-suggesting it would be noise.
    """
    return (
        select(column)
        .where(
            RiskClassification.system_id == AISystem.id,
            RiskClassification.status == "pending_review",
        )
        .order_by(RiskClassification.created_at.desc())
        .limit(1)
        .correlate(AISystem)
        .scalar_subquery()
    )


def _shadow_filter(org_id: uuid.UUID) -> list[Any]:
    return [
        AISystem.org_id == org_id,
        AISystem.origin == "discovered",
        func.cardinality(AISystem.agent_ids) == 0,
        AISystem.status == "active",
    ]


async def list_shadow_systems(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 100,
) -> list[ShadowSystem]:
    """Systems a probe found that no Parry agent covers.

    The whole point of the discovery layer: present in the environment,
    invisible to runtime monitoring.
    """
    result = await db.execute(
        select(
            AISystem,
            _latest_pending(RiskClassification.risk_tier).label("proposed_risk_level"),
            _latest_pending(RiskClassification.reasoning).label("proposed_reasoning"),
        )
        .where(*_shadow_filter(org_id))
        .order_by(AISystem.last_seen_at.desc().nullslast())
        .limit(limit)
    )
    return [
        ShadowSystem(
            id=system.id,
            name=system.name,
            provider_name=system.provider_name,
            risk_level=system.risk_level,
            proposed_risk_level=tier,
            proposed_reasoning=reasoning,
            discovery_source=system.discovery_source,
            first_seen_at=system.first_seen_at,
            last_seen_at=system.last_seen_at,
        )
        for system, tier, reasoning in result.all()
    ]


async def shadow_summary(db: AsyncSession, *, org_id: uuid.UUID) -> dict[str, Any]:
    """Counts for the dashboard header, by the tier that gets displayed.

    Grouped on the effective tier rather than the stored one. Grouping on
    the stored column put every discovered system in a single
    'unclassified' bucket, which told the viewer nothing.
    """
    effective = func.coalesce(
        func.nullif(AISystem.risk_level, "unclassified"),
        _latest_pending(RiskClassification.risk_tier),
        "unclassified",
    )
    result = await db.execute(
        select(effective.label("tier"), func.count())
        .where(*_shadow_filter(org_id))
        .group_by(effective)
    )
    by_tier = {tier: count for tier, count in result.all()}
    return {"total": sum(by_tier.values()), "by_risk_level": by_tier}
