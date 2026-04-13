"""Org-wide spend summary endpoint.

Aggregates estimated_cost_usd across all agents in the org, broken down
by period (last hour, last 24 h, last 30 d), plus a top-5 per-agent
breakdown and the org-level budget cap if one exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Agent, AgentBudget, AgentEvent, Org
from app.db.session import get_db
from app.schemas.base import ParrySchema

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────


class AgentSpendEntry(ParrySchema):
    agent_id: uuid.UUID
    agent_name: str
    month_spend: float


class OrgSpendSummary(ParrySchema):
    hour_spend: float
    day_spend: float
    month_spend: float
    top_agents: list[AgentSpendEntry]
    total_budget_cap: float | None


# ── Route ────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=OrgSpendSummary,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def org_spend_summary(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> OrgSpendSummary:
    """Aggregate spend across all agents in the org.

    Queries agent_events directly (always filtered by agent_id + time range
    to avoid full-table scans on the TimescaleDB hypertable). Returns spend
    for the last hour, last 24 h, and last 30 days, together with the top 5
    agents by month spend and the org-wide budget cap if one is configured.
    """
    now = datetime.now(UTC)
    cutoff_hour = now - timedelta(hours=1)
    cutoff_day = now - timedelta(hours=24)
    cutoff_month = now - timedelta(days=30)

    # Resolve all agent IDs for this org in one query.
    agent_rows = (
        await db.execute(
            select(Agent.id, Agent.name).where(Agent.org_id == org.id)
        )
    ).all()

    if not agent_rows:
        return OrgSpendSummary(
            hour_spend=0.0,
            day_spend=0.0,
            month_spend=0.0,
            top_agents=[],
            total_budget_cap=None,
        )

    agent_ids = [row[0] for row in agent_rows]
    agent_names: dict[uuid.UUID, str] = {row[0]: row[1] for row in agent_rows}

    # ── Period aggregates ────────────────────────────────────────

    async def _sum_spend(cutoff: datetime) -> float:
        result = await db.execute(
            select(func.coalesce(func.sum(AgentEvent.estimated_cost_usd), 0.0)).where(
                AgentEvent.agent_id.in_(agent_ids),
                AgentEvent.timestamp >= cutoff,
            )
        )
        return float(result.scalar_one())

    hour_spend = await _sum_spend(cutoff_hour)
    day_spend = await _sum_spend(cutoff_day)
    month_spend = await _sum_spend(cutoff_month)

    # ── Per-agent breakdown (month, top 5) ───────────────────────

    per_agent_result = await db.execute(
        select(
            AgentEvent.agent_id,
            func.coalesce(func.sum(AgentEvent.estimated_cost_usd), 0.0).label("total"),
        )
        .where(
            AgentEvent.agent_id.in_(agent_ids),
            AgentEvent.timestamp >= cutoff_month,
        )
        .group_by(AgentEvent.agent_id)
        .order_by(func.sum(AgentEvent.estimated_cost_usd).desc())
        .limit(5)
    )

    top_agents = [
        AgentSpendEntry(
            agent_id=row.agent_id,
            agent_name=agent_names.get(row.agent_id, "Unknown"),
            month_spend=float(row.total),
        )
        for row in per_agent_result.all()
    ]

    # ── Org-wide budget cap (agent_id IS NULL, period = "month") ─

    budget_result = await db.execute(
        select(AgentBudget.cap_usd).where(
            AgentBudget.org_id == org.id,
            AgentBudget.agent_id.is_(None),
            AgentBudget.period == "month",
            AgentBudget.enabled.is_(True),
        )
    )
    budget_row = budget_result.scalar_one_or_none()
    total_budget_cap = float(budget_row) if budget_row is not None else None

    log.debug(
        "spend.summary",
        org_id=str(org.id),
        hour=hour_spend,
        day=day_spend,
        month=month_spend,
    )

    return OrgSpendSummary(
        hour_spend=hour_spend,
        day_spend=day_spend,
        month_spend=month_spend,
        top_agents=top_agents,
        total_budget_cap=total_budget_cap,
    )
