"""Budget CRUD routes.

Dashboard endpoints for managing per-agent / org-wide spend caps.
All mutations are audit-logged.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import AgentBudget, Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────


class BudgetResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    period: str
    cap_usd: float
    enabled: bool
    alert_at_pcts: list[int]


class BudgetUpsert(ParrySchema):
    agent_id: uuid.UUID | None = None
    period: str
    cap_usd: float
    enabled: bool = True
    alert_at_pcts: list[int] = [75, 90, 100]


# ── Routes ──────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[BudgetResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_budgets(
    org: Org = Depends(lambda org_actor=Depends(require_role(Role.VIEWER)): org_actor[0]),
    db: AsyncSession = Depends(get_db),
    agent_id: uuid.UUID | None = Query(None),
) -> list[BudgetResponse]:
    """List budgets for an agent (or all org budgets if agent_id omitted)."""
    query = select(AgentBudget).where(AgentBudget.org_id == org.id)
    if agent_id is not None:
        query = query.where(AgentBudget.agent_id == agent_id)
    result = await db.execute(query)
    budgets = list(result.scalars().all())
    return [BudgetResponse.model_validate(b) for b in budgets]


@router.put("", response_model=BudgetResponse)
async def upsert_budget(
    body: BudgetUpsert,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> BudgetResponse:
    """Create or update a budget. Upserts on (org_id, agent_id, period)."""
    org, actor = org_actor

    if body.period not in ("hour", "day", "month"):
        raise HTTPException(status_code=400, detail="period must be hour, day, or month")
    if body.cap_usd <= 0:
        raise HTTPException(status_code=400, detail="cap_usd must be positive")

    # Look for existing
    query = select(AgentBudget).where(
        AgentBudget.org_id == org.id,
        AgentBudget.period == body.period,
    )
    if body.agent_id is not None:
        query = query.where(AgentBudget.agent_id == body.agent_id)
    else:
        query = query.where(AgentBudget.agent_id.is_(None))

    result = await db.execute(query)
    budget = result.scalar_one_or_none()

    if budget is not None:
        before = {
            "cap_usd": float(budget.cap_usd),
            "enabled": budget.enabled,
            "alert_at_pcts": budget.alert_at_pcts,
        }
        budget.cap_usd = body.cap_usd
        budget.enabled = body.enabled
        budget.alert_at_pcts = body.alert_at_pcts
        action = "budget.updated"
    else:
        before = None
        budget = AgentBudget(
            org_id=org.id,
            agent_id=body.agent_id,
            period=body.period,
            cap_usd=body.cap_usd,
            enabled=body.enabled,
            alert_at_pcts=body.alert_at_pcts,
        )
        db.add(budget)
        action = "budget.created"

    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action=action,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="budget",
        resource_id=str(budget.id),
        details={"before": before, "after": body.model_dump()},
    )
    await db.commit()
    await db.refresh(budget)

    return BudgetResponse.model_validate(budget)


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a budget."""
    org, actor = org_actor

    result = await db.execute(
        select(AgentBudget).where(AgentBudget.id == budget_id, AgentBudget.org_id == org.id)
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="budget.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="budget",
        resource_id=str(budget_id),
        details={"period": budget.period, "cap_usd": float(budget.cap_usd)},
    )
    await db.delete(budget)
    await db.commit()
