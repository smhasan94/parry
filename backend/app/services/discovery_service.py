"""Turn probe hits into rows in the AI system register.

A probe tells you a vendor is in use. This module decides whether that
means a new register entry or a fresher timestamp on an existing one, and
seeds the catalog's default risk tier as a *pending* classification —
never an approved one. A machine-proposed Annex III tier is a draft for a
human to approve, not a compliance fact.
"""

from __future__ import annotations

import uuid
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


async def list_shadow_systems(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 100,
) -> list[AISystem]:
    """Systems a probe found that no Parry agent covers.

    The whole point of the discovery layer: present in the environment,
    invisible to runtime monitoring.
    """
    result = await db.execute(
        select(AISystem)
        .where(
            AISystem.org_id == org_id,
            AISystem.origin == "discovered",
            func.cardinality(AISystem.agent_ids) == 0,
            AISystem.status == "active",
        )
        .order_by(AISystem.last_seen_at.desc().nullslast())
        .limit(limit)
    )
    return list(result.scalars().all())


async def shadow_summary(db: AsyncSession, *, org_id: uuid.UUID) -> dict[str, Any]:
    """Counts for the dashboard header, by risk tier."""
    result = await db.execute(
        select(AISystem.risk_level, func.count())
        .where(
            AISystem.org_id == org_id,
            AISystem.origin == "discovered",
            func.cardinality(AISystem.agent_ids) == 0,
            AISystem.status == "active",
        )
        .group_by(AISystem.risk_level)
    )
    by_tier = {tier: count for tier, count in result.all()}
    return {"total": sum(by_tier.values()), "by_risk_level": by_tier}
