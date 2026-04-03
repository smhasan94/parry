import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Agent

log = structlog.get_logger()


async def list_agents(
    db: AsyncSession,
    org_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Agent], str | None]:
    query = select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at.desc())

    if cursor:
        cursor_id = uuid.UUID(cursor)
        cursor_agent = await db.get(Agent, cursor_id)
        if cursor_agent:
            query = query.where(Agent.created_at < cursor_agent.created_at)

    query = query.limit(limit + 1)
    result = await db.execute(query)
    agents = list(result.scalars().all())

    next_cursor = None
    if len(agents) > limit:
        agents = agents[:limit]
        next_cursor = str(agents[-1].id)

    return agents, next_cursor


async def get_agent(db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError("Agent", str(agent_id))
    return agent


async def create_agent(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    # Check for duplicate name within org
    result = await db.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.name == name)
    )
    if result.scalar_one_or_none():
        raise ConflictError(f"Agent with name '{name}' already exists in this org")

    agent = Agent(
        org_id=org_id,
        name=name,
        description=description,
        metadata_=metadata,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    log.info("agent.created", agent_id=str(agent.id), org_id=str(org_id), name=name)
    return agent


async def update_agent(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    **updates: Any,
) -> Agent:
    agent = await get_agent(db, org_id, agent_id)

    for key, value in updates.items():
        if value is not None:
            if key == "metadata":
                setattr(agent, "metadata_", value)
            else:
                setattr(agent, key, value)

    await db.flush()
    await db.refresh(agent)
    log.info("agent.updated", agent_id=str(agent_id))
    return agent


async def delete_agent(db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    """Soft-delete an agent by marking it inactive."""
    agent = await get_agent(db, org_id, agent_id)
    agent.is_active = False
    await db.flush()
    await db.refresh(agent)
    log.info("agent.deleted", agent_id=str(agent_id))
    return agent
