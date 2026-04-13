"""Agent group CRUD + assignment routes."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import agent_group_service, audit_service

log = structlog.get_logger()
router = APIRouter()


class GroupCreateRequest(ParrySchema):
    name: str
    description: str | None = None


class GroupUpdateRequest(ParrySchema):
    name: str | None = None
    description: str | None = None


class GroupResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    agent_count: int = 0


class AssignGroupRequest(ParrySchema):
    group_id: uuid.UUID | None = None


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[GroupResponse]:
    org, _ = org_actor
    groups = await agent_group_service.list_groups(db, org.id)
    return [
        GroupResponse(
            **GroupResponse.model_validate(g).model_dump(exclude={"agent_count"}),
            agent_count=len(g.agents) if g.agents else 0,
        )
        for g in groups
    ]


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    body: GroupCreateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    org, actor = org_actor
    group = await agent_group_service.create_group(
        db, org.id, name=body.name, description=body.description,
    )
    await audit_service.log_action(
        db, org_id=org.id, action="agent_group.created",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="agent_group",
        resource_id=str(group.id), details={"name": body.name},
    )
    await db.commit()
    return GroupResponse.model_validate(group)


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    org, _ = org_actor
    group = await agent_group_service.get_group(db, org.id, group_id)
    resp = GroupResponse.model_validate(group)
    resp.agent_count = len(group.agents) if group.agents else 0
    return resp


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    org, actor = org_actor
    group = await agent_group_service.update_group(
        db, org.id, group_id, **body.model_dump(exclude_unset=True),
    )
    await audit_service.log_action(
        db, org_id=org.id, action="agent_group.updated",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="agent_group",
        resource_id=str(group_id),
    )
    await db.commit()
    return GroupResponse.model_validate(group)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    await agent_group_service.delete_group(db, org.id, group_id)
    await audit_service.log_action(
        db, org_id=org.id, action="agent_group.deleted",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="agent_group",
        resource_id=str(group_id),
    )
    await db.commit()


@router.patch("/{group_id}/agents/{agent_id}")
async def assign_agent(
    group_id: uuid.UUID,
    agent_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org, actor = org_actor
    await agent_group_service.assign_agent_to_group(
        db, org.id, agent_id, group_id,
    )
    await audit_service.log_action(
        db, org_id=org.id, action="agent_group.agent_assigned",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="agent",
        resource_id=str(agent_id),
        details={"group_id": str(group_id), "group_name": None},
    )
    await db.commit()
    return {"agent_id": str(agent_id), "group_id": str(group_id)}


@router.delete("/{group_id}/agents/{agent_id}", status_code=204)
async def unassign_agent(
    group_id: uuid.UUID,
    agent_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    await agent_group_service.assign_agent_to_group(db, org.id, agent_id, None)
    await audit_service.log_action(
        db, org_id=org.id, action="agent_group.agent_unassigned",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        actor_label=actor.label, resource_type="agent",
        resource_id=str(agent_id),
        details={"removed_from_group": str(group_id)},
    )
    await db.commit()
