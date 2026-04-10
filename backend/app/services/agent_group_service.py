"""Agent group CRUD service."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Agent, AgentGroup

log = structlog.get_logger()


async def list_groups(
    db: AsyncSession, org_id: uuid.UUID
) -> list[AgentGroup]:
    result = await db.execute(
        select(AgentGroup)
        .where(AgentGroup.org_id == org_id)
        .order_by(AgentGroup.name)
    )
    return list(result.scalars().all())


async def get_group(
    db: AsyncSession, org_id: uuid.UUID, group_id: uuid.UUID
) -> AgentGroup:
    result = await db.execute(
        select(AgentGroup).where(
            AgentGroup.id == group_id, AgentGroup.org_id == org_id
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise NotFoundError("AgentGroup", str(group_id))
    return group


async def create_group(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    description: str | None = None,
) -> AgentGroup:
    # Check uniqueness
    existing = await db.execute(
        select(AgentGroup).where(
            AgentGroup.org_id == org_id, AgentGroup.name == name
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"Group '{name}' already exists")

    group = AgentGroup(org_id=org_id, name=name, description=description)
    db.add(group)
    await db.flush()
    await db.refresh(group)
    log.info("agent_group.created", group_id=str(group.id), name=name)
    return group


async def update_group(
    db: AsyncSession,
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    **updates: Any,
) -> AgentGroup:
    group = await get_group(db, org_id, group_id)
    for key, value in updates.items():
        if value is not None:
            setattr(group, key, value)
    await db.flush()
    await db.refresh(group)
    log.info("agent_group.updated", group_id=str(group_id))
    return group


async def delete_group(
    db: AsyncSession, org_id: uuid.UUID, group_id: uuid.UUID
) -> None:
    group = await get_group(db, org_id, group_id)
    # Unassign all agents first (cascade SET NULL handles FK, but
    # we want to clear group_id explicitly for the audit trail)
    agents_result = await db.execute(
        select(Agent).where(Agent.group_id == group_id)
    )
    for agent in agents_result.scalars().all():
        agent.group_id = None

    await db.delete(group)
    await db.flush()
    log.info("agent_group.deleted", group_id=str(group_id))


async def assign_agent_to_group(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    group_id: uuid.UUID | None,
) -> Agent:
    """Assign an agent to a group (or unassign with group_id=None)."""
    from app.services.agent_service import get_agent

    agent = await get_agent(db, org_id, agent_id)
    if group_id is not None:
        # Verify group belongs to same org
        await get_group(db, org_id, group_id)
    agent.group_id = group_id
    await db.flush()
    await db.refresh(agent)
    log.info(
        "agent_group.assignment",
        agent_id=str(agent_id),
        group_id=str(group_id) if group_id else None,
    )
    return agent
