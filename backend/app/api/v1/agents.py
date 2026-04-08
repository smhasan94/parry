import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Agent, Org
from app.db.session import get_db
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.services import agent_service, audit_service, plan_service, session_service
from app.services.agent_stats_service import get_or_build_agent_stats
from app.services.baseline_service import MIN_EVENTS, compute_baseline
from app.services.health_score_service import get_or_compute_health

router = APIRouter()


@router.get(
    "",
    response_model=list[AgentResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_agents(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> list[AgentResponse]:
    agents, next_cursor = await agent_service.list_agents(db, org.id, cursor, limit)
    responses: list[AgentResponse] = []
    for a in agents:
        resp = AgentResponse.model_validate(a)
        health = await get_or_compute_health(db, a.id)
        resp.health_score = health["score"]
        resp.health_grade = health["grade"]
        resp.health_components = health["components"]
        responses.append(resp)
    return responses


@router.post("/baselines/recompute-all")
async def recompute_all_baselines(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Force-recompute baselines for every agent in the org.

    Returns counts of recomputed/skipped/errored agents. Skipped agents are
    those without enough events (< MIN_EVENTS).
    """
    org, actor = org_actor
    agents = (await db.execute(select(Agent).where(Agent.org_id == org.id))).scalars().all()

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


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_agent(
    agent_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await agent_service.get_agent(db, org.id, agent_id)
    resp = AgentResponse.model_validate(agent)
    health = await get_or_compute_health(db, agent.id)
    resp.health_score = health["score"]
    resp.health_grade = health["grade"]
    resp.health_components = health["components"]
    return resp


@router.get(
    "/{agent_id}/stats",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_agent_stats(
    agent_id: uuid.UUID,
    window: str = Query("30d", pattern="^(7d|30d|90d)$"),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Agent behavioural stats for the charts on AgentDetailPage.

    Returns event volume, top tool calls, model usage, anomaly trend,
    and per-detector triggered counts over the requested window. Read
    through a 5 minute Redis cache.
    """
    # Confirm the agent belongs to the caller's org before leaking any
    # aggregate data.
    await agent_service.get_agent(db, org.id, agent_id)
    try:
        return await get_or_build_agent_stats(db, agent_id, window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/{agent_id}/sessions",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_agent_sessions_route(
    agent_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent sessions for an agent, newest first.

    Used by the Sessions tab on AgentDetailPage. Each entry carries
    its event count so the UI can summarize without fetching full
    session payloads.
    """
    sessions = await session_service.list_agent_sessions(db, agent_id, org.id, limit=limit)
    if sessions is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return sessions


@router.post(
    "",
    response_model=AgentResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_agent(
    body: AgentCreate,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    await plan_service.check_agent_limit(db, org)
    agent = await agent_service.create_agent(
        db,
        org_id=org.id,
        name=body.name,
        description=body.description,
        metadata=body.metadata,
    )
    await db.commit()
    return AgentResponse.model_validate(agent)


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
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
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
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


@router.delete(
    "/{agent_id}",
    status_code=204,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def delete_agent(
    agent_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    await agent_service.delete_agent(db, org_id=org.id, agent_id=agent_id)
    await db.commit()
