"""Plan limits + enforcement.

Single source of truth for the per-tier limit table and the helpers
that enforce it at API boundaries. Callers live in agents.py
(agent creation), events.py (ingest), and the custom-rules /
compliance-report paths (feature gates). All raise HTTP 402 with
``X-Upgrade-Required`` so the dashboard can detect the quota error
and show an upgrade modal.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentEvent, Org, Plan

log = structlog.get_logger()


# Limits per plan. ``None`` means unlimited.
PLAN_LIMITS: dict[Plan, dict[str, Any]] = {
    Plan.FREE: {
        "max_agents": 1,
        "max_events_per_month": 10_000,
        "retention_days": 30,
        "custom_rules": False,
        "compliance_export": False,
    },
    Plan.GROWTH: {
        "max_agents": 10,
        "max_events_per_month": 100_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
    },
    Plan.PRO: {
        "max_agents": 50,
        "max_events_per_month": 1_000_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
    },
    Plan.ENTERPRISE: {
        "max_agents": None,
        "max_events_per_month": None,
        "retention_days": None,
        "custom_rules": True,
        "compliance_export": True,
    },
}


def get_limits(plan: Plan) -> dict[str, Any]:
    """Return the limit dict for a plan (safe copy)."""
    return dict(PLAN_LIMITS[plan])


def _upgrade_required(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=detail,
        headers={"X-Upgrade-Required": "true"},
    )


async def _count_agents(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Agent).where(Agent.org_id == org_id)
    )
    return int(result.scalar_one() or 0)


async def _count_events_this_month(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Rolling 30-day event count for the org.

    Hypertable-safe: we iterate agent ids and filter each subquery by
    agent_id + timestamp range so queries stay chunk-aware.
    """
    since = datetime.now(UTC) - timedelta(days=30)
    agent_ids = (
        (await db.execute(select(Agent.id).where(Agent.org_id == org_id)))
        .scalars()
        .all()
    )
    if not agent_ids:
        return 0

    total = 0
    for agent_id in agent_ids:
        row = await db.execute(
            select(func.count())
            .select_from(AgentEvent)
            .where(
                AgentEvent.agent_id == agent_id,
                AgentEvent.timestamp >= since,
            )
        )
        total += int(row.scalar_one() or 0)
    return total


async def check_agent_limit(db: AsyncSession, org: Org) -> None:
    """Raise 402 if the org can't create another agent."""
    limits = PLAN_LIMITS[org.plan]
    max_agents = limits["max_agents"]
    if max_agents is None:
        return
    count = await _count_agents(db, org.id)
    if count >= max_agents:
        log.info(
            "plan.agent_limit_hit",
            org_id=str(org.id),
            plan=org.plan.value,
            current=count,
            limit=max_agents,
        )
        raise _upgrade_required(
            f"Agent limit reached for the {org.plan.value} plan "
            f"({max_agents}). Upgrade to add more agents."
        )


async def check_event_quota(db: AsyncSession, org: Org) -> None:
    """Raise 402 if the org is over its rolling 30-day event quota."""
    limits = PLAN_LIMITS[org.plan]
    max_events = limits["max_events_per_month"]
    if max_events is None:
        return
    count = await _count_events_this_month(db, org.id)
    if count >= max_events:
        log.info(
            "plan.event_quota_hit",
            org_id=str(org.id),
            plan=org.plan.value,
            current=count,
            limit=max_events,
        )
        raise _upgrade_required(
            f"Monthly event limit reached for the {org.plan.value} plan "
            f"({max_events}). Upgrade to continue."
        )


def require_feature(org: Org, feature: str) -> None:
    """Gate optional features (custom_rules, compliance_export).

    Synchronous — no DB needed, just the limit table lookup.
    """
    limits = PLAN_LIMITS[org.plan]
    if not limits.get(feature, False):
        raise _upgrade_required(
            f"The '{feature}' feature is not available on the "
            f"{org.plan.value} plan. Upgrade to unlock it."
        )


async def count_events_since(
    db: AsyncSession, org_id: uuid.UUID, since: datetime
) -> int:
    """Events ingested for an org since a cutoff, agent-by-agent.

    Used by the daily metered usage reporter to produce a 24h count
    per org without scanning the whole hypertable.
    """
    agent_ids = (
        (await db.execute(select(Agent.id).where(Agent.org_id == org_id)))
        .scalars()
        .all()
    )
    total = 0
    for agent_id in agent_ids:
        row = await db.execute(
            select(func.count())
            .select_from(AgentEvent)
            .where(
                AgentEvent.agent_id == agent_id,
                AgentEvent.timestamp >= since,
            )
        )
        total += int(row.scalar_one() or 0)
    return total
