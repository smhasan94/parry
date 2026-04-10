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
        "red_team": False,
        "red_team_live": False,
        "mcp_security": False,
        "cost_exploit_detection": False,
        "budget_enforcement": False,
        "agent_permissions": False,
        "ai_system_register": False,
        "fria_generator": False,
        "serious_incident_reporting": False,
        "compliance_posture": False,
        "auditor_bundle": False,
    },
    Plan.GROWTH: {
        "max_agents": 10,
        "max_events_per_month": 100_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
        "red_team": True,
        "red_team_live": False,
        "mcp_security": True,
        "cost_exploit_detection": True,
        "budget_enforcement": True,
        "agent_permissions": True,
        "ai_system_register": False,
        "fria_generator": False,
        "serious_incident_reporting": False,
        "compliance_posture": False,
        "auditor_bundle": False,
    },
    Plan.PRO: {
        "max_agents": 50,
        "max_events_per_month": 1_000_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
        "red_team": True,
        "red_team_live": True,
        "mcp_security": True,
        "cost_exploit_detection": True,
        "budget_enforcement": True,
        "agent_permissions": True,
        "ai_system_register": True,
        "fria_generator": False,
        "serious_incident_reporting": False,
        "compliance_posture": True,
        "auditor_bundle": False,
    },
    Plan.ENTERPRISE: {
        "max_agents": None,
        "max_events_per_month": None,
        "retention_days": None,
        "custom_rules": True,
        "compliance_export": True,
        "red_team": True,
        "red_team_live": True,
        "mcp_security": True,
        "cost_exploit_detection": True,
        "budget_enforcement": True,
        "agent_permissions": True,
        "ai_system_register": True,
        "fria_generator": True,
        "serious_incident_reporting": True,
        "compliance_posture": True,
        "auditor_bundle": True,
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
    result = await db.execute(select(func.count()).select_from(Agent).where(Agent.org_id == org_id))
    return int(result.scalar_one() or 0)


async def _count_events_this_month(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Rolling 30-day event count for the org.

    Called on every ``POST /events/ingest`` so this MUST be a single
    round trip. The naive "iterate agent ids, one count per agent"
    pattern turns a single ingest into 1 + N queries and was the
    worst hot-path offender in the backend. We push the agent filter
    into a subquery so the planner can still pick a chunk-aware plan
    on the TimescaleDB hypertable while we pay for one roundtrip.
    """
    since = datetime.now(UTC) - timedelta(days=30)
    agent_ids_subq = select(Agent.id).where(Agent.org_id == org_id).scalar_subquery()
    result = await db.execute(
        select(func.count())
        .select_from(AgentEvent)
        .where(
            AgentEvent.agent_id.in_(agent_ids_subq),
            AgentEvent.timestamp >= since,
        )
    )
    return int(result.scalar_one() or 0)


def _effective_limits(org: Org) -> dict[str, Any]:
    """Return the limit dict to enforce, considering on-prem mode.

    In on-prem deployments the signed license file is the source of
    truth — the ``orgs.plan`` column is ignored because billing
    doesn't exist in that world. The license is loaded once at
    startup (see ``core.on_prem``).
    """
    from app.core import on_prem

    if on_prem.is_on_prem():
        lic = on_prem.get_license()
        if lic is None:
            # Startup should have failed loudly if we get here. Fail
            # closed rather than silently granting unlimited access.
            return {
                "max_agents": 0,
                "max_events_per_month": 0,
                "retention_days": None,
                "custom_rules": False,
                "compliance_export": False,
            }
        return {
            "max_agents": lic.max_agents,
            "max_events_per_month": lic.max_events_per_month,
            "retention_days": None,
            "custom_rules": lic.has_feature("custom_rules"),
            "compliance_export": lic.has_feature("compliance_export"),
        }
    return dict(PLAN_LIMITS[org.plan])


async def check_agent_limit(db: AsyncSession, org: Org) -> None:
    """Raise 402 if the org can't create another agent."""
    limits = _effective_limits(org)
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
            f"Agent limit reached ({max_agents}). "
            "Upgrade plan or license to add more agents."
        )


async def check_event_quota(db: AsyncSession, org: Org) -> None:
    """Raise 402 if the org is over its rolling 30-day event quota."""
    limits = _effective_limits(org)
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
            f"Monthly event limit reached ({max_events}). "
            "Upgrade plan or license to continue."
        )


def require_feature(org: Org, feature: str) -> None:
    """Gate optional features (custom_rules, compliance_export).

    Synchronous — no DB needed, just the limit table lookup.
    """
    limits = _effective_limits(org)
    if not limits.get(feature, False):
        raise _upgrade_required(
            f"The '{feature}' feature is not available on this plan / license. "
            "Upgrade to unlock it."
        )


async def count_events_since(db: AsyncSession, org_id: uuid.UUID, since: datetime) -> int:
    """Events ingested for an org since a cutoff.

    Used by the daily metered usage reporter. Single-query so a
    50-agent org doesn't turn into 50 round trips per run.
    """
    agent_ids_subq = select(Agent.id).where(Agent.org_id == org_id).scalar_subquery()
    result = await db.execute(
        select(func.count())
        .select_from(AgentEvent)
        .where(
            AgentEvent.agent_id.in_(agent_ids_subq),
            AgentEvent.timestamp >= since,
        )
    )
    return int(result.scalar_one() or 0)
