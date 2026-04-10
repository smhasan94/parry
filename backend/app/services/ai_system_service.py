"""CRUD for the Article 26 AI System Register."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import AISystem, AISystemSupplier

log = structlog.get_logger()


async def list_systems(
    db: AsyncSession,
    org_id: uuid.UUID,
    risk_level: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[AISystem], str | None]:
    query = (
        select(AISystem)
        .where(AISystem.org_id == org_id)
        .order_by(AISystem.created_at.desc())
    )
    if risk_level:
        query = query.where(AISystem.risk_level == risk_level)
    if cursor:
        cursor_system = await db.get(AISystem, uuid.UUID(cursor))
        if cursor_system:
            query = query.where(AISystem.created_at < cursor_system.created_at)
    query = query.limit(limit + 1)
    result = await db.execute(query)
    systems = list(result.scalars().all())

    next_cursor = None
    if len(systems) > limit:
        systems = systems[:limit]
        next_cursor = str(systems[-1].id)

    return systems, next_cursor


async def get_system(
    db: AsyncSession, org_id: uuid.UUID, system_id: uuid.UUID
) -> AISystem:
    result = await db.execute(
        select(AISystem).where(AISystem.id == system_id, AISystem.org_id == org_id)
    )
    system = result.scalar_one_or_none()
    if system is None:
        raise NotFoundError("AISystem", str(system_id))
    return system


async def create_system(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    name: str,
    risk_level: str,
    intended_purpose: str,
    description: str | None = None,
    deployer_name: str | None = None,
    provider_name: str | None = None,
    provider_contact: str | None = None,
    deployment_date: Any = None,
    agent_ids: list[uuid.UUID] | None = None,
    annex_iii_category: str | None = None,
    jurisdiction: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AISystem:
    # Auto-derive FRIA obligation from risk level
    fria_required = risk_level == "high"
    fria_status = "missing" if fria_required else "not_required"

    system = AISystem(
        org_id=org_id,
        name=name,
        description=description,
        risk_level=risk_level,
        intended_purpose=intended_purpose,
        deployer_name=deployer_name,
        provider_name=provider_name,
        provider_contact=provider_contact,
        deployment_date=deployment_date,
        fria_required=fria_required,
        fria_status=fria_status,
        agent_ids=agent_ids or [],
        annex_iii_category=annex_iii_category,
        jurisdiction=jurisdiction,
        metadata_=metadata,
    )
    db.add(system)
    await db.flush()
    await db.refresh(system)
    log.info(
        "ai_system.created",
        system_id=str(system.id),
        org_id=str(org_id),
        risk_level=risk_level,
    )
    return system


async def update_system(
    db: AsyncSession,
    org_id: uuid.UUID,
    system_id: uuid.UUID,
    **updates: Any,
) -> AISystem:
    system = await get_system(db, org_id, system_id)
    for key, value in updates.items():
        if value is not None:
            if key == "metadata":
                system.metadata_ = value
            else:
                setattr(system, key, value)

    # Re-derive FRIA obligation if risk_level changed
    if "risk_level" in updates and updates["risk_level"] is not None:
        system.fria_required = system.risk_level == "high"
        if system.fria_required and system.fria_status == "not_required":
            system.fria_status = "missing"
        elif not system.fria_required:
            system.fria_status = "not_required"

    await db.flush()
    await db.refresh(system)
    log.info("ai_system.updated", system_id=str(system_id))
    return system


async def delete_system(
    db: AsyncSession, org_id: uuid.UUID, system_id: uuid.UUID
) -> None:
    system = await get_system(db, org_id, system_id)
    await db.delete(system)
    await db.flush()
    log.info("ai_system.deleted", system_id=str(system_id))


async def list_suppliers(
    db: AsyncSession, system_id: uuid.UUID
) -> list[AISystemSupplier]:
    result = await db.execute(
        select(AISystemSupplier)
        .where(AISystemSupplier.system_id == system_id)
        .order_by(AISystemSupplier.last_used_at.desc())
    )
    return list(result.scalars().all())
