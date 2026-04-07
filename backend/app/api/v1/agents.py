import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import Agent, Org
from app.db.session import get_db
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.services import agent_service, audit_service
from app.services.baseline_service import MIN_EVENTS, compute_baseline

router = APIRouter()


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> list[AgentResponse]:
    agents, next_cursor = await agent_service.list_agents(db, org.id, cursor, limit)
    return [AgentResponse.model_validate(a) for a in agents]


@router.post("/baselines/recompute-all")
async def recompute_all_baselines(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Force-recompute baselines for every agent in the org.

    Returns counts of recomputed/skipped/errored agents. Skipped agents are
    those without enough events (< MIN_EVENTS).
    """
    org, actor = org_actor
    agents = (
        (await db.execute(select(Agent).where(Agent.org_id == org.id))).scalars().all()
    )

    recomputed = 0
    skipped = 0
    errored = 0

    for agent in agents:
        try:
            before = dict(agent.baseline) if agent.baseline else None
            baseline = await compute_baseline(db, agent.id)
            if baseline is None:
                skipped += 1
                continue
            agent.baseline = baseline
            await db.flush()
            await audit_service.log_action(
                db,
                org_id=org.id,
                action="baseline.recomputed",
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                actor_label=actor.label,
                resource_type="agent",
                resource_id=str(agent.id),
                details={"before": before, "after": baseline, "reason": "manual_bulk"},
            )
            recomputed += 1
        except Exception:
            errored += 1

    await db.commit()
    return {"recomputed": recomputed, "skipped": skipped, "errored": errored}


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await agent_service.get_agent(db, org.id, agent_id)
    return AgentResponse.model_validate(agent)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await agent_service.create_agent(
        db,
        org_id=org.id,
        name=body.name,
        description=body.description,
        metadata=body.metadata,
    )
    await db.commit()
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await agent_service.update_agent(
        db,
        org_id=org.id,
        agent_id=agent_id,
        **body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/baseline/recompute", response_model=AgentResponse)
async def recompute_baseline(
    agent_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Force-recompute the agent's behavioral baseline from current event history."""
    org, actor = org_actor
    agent = await agent_service.get_agent(db, org.id, agent_id)
    before = dict(agent.baseline) if agent.baseline else None
    baseline = await compute_baseline(db, agent.id)
    if baseline is None:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough events to compute baseline (need at least {MIN_EVENTS})",
        )
    agent.baseline = baseline
    await db.flush()
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="baseline.recomputed",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="agent",
        resource_id=str(agent.id),
        details={"before": before, "after": baseline},
    )
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    await agent_service.delete_agent(db, org_id=org.id, agent_id=agent_id)
    await db.commit()
