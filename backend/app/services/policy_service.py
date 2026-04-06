import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Policy

log = structlog.get_logger()


async def list_policies(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[Policy]:
    result = await db.execute(
        select(Policy).where(Policy.org_id == org_id).order_by(Policy.created_at.desc())
    )
    return list(result.scalars().all())


async def get_policy(db: AsyncSession, org_id: uuid.UUID, policy_id: uuid.UUID) -> Policy:
    result = await db.execute(select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id))
    policy = result.scalar_one_or_none()
    if policy is None:
        raise NotFoundError("Policy", str(policy_id))
    return policy


async def create_policy(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    **kwargs: Any,
) -> Policy:
    policy = Policy(org_id=org_id, name=name, **kwargs)
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    log.info("policy.created", policy_id=str(policy.id), org_id=str(org_id), name=name)
    return policy


async def update_policy(
    db: AsyncSession,
    org_id: uuid.UUID,
    policy_id: uuid.UUID,
    **updates: Any,
) -> Policy:
    policy = await get_policy(db, org_id, policy_id)

    for key, value in updates.items():
        if value is not None:
            setattr(policy, key, value)

    await db.flush()
    await db.refresh(policy)
    log.info("policy.updated", policy_id=str(policy_id))
    return policy


async def delete_policy(db: AsyncSession, org_id: uuid.UUID, policy_id: uuid.UUID) -> None:
    policy = await get_policy(db, org_id, policy_id)
    await db.delete(policy)
    await db.flush()
    log.info("policy.deleted", policy_id=str(policy_id))
