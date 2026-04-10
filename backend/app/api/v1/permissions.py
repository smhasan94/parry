"""Agent permission boundary CRUD routes.

Manage per-agent and org-wide default tool permissions.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, permission_service, plan_service

log = structlog.get_logger()
router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────


class PermissionRequest(ParrySchema):
    mode: str = "disabled"  # enforcing | dry_run | disabled
    default_action: str = "allow"  # allow | deny
    allowed_tools: list[str] = []
    blocked_tools: list[str] = []


class PermissionResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID | None
    mode: str
    default_action: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    created_at: str
    updated_at: str


# ── Per-agent permissions ───────────────────────────────────────


@router.get(
    "/agents/{agent_id}/permissions",
    response_model=PermissionResponse | None,
)
async def get_agent_permissions(
    agent_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse | None:
    org, _ = org_actor
    plan_service.require_feature(org, "agent_permissions")
    perm = await permission_service.get_permission(db, org.id, agent_id)
    if perm is None:
        return None
    return PermissionResponse.model_validate(perm)


@router.put(
    "/agents/{agent_id}/permissions",
    response_model=PermissionResponse,
)
async def set_agent_permissions(
    agent_id: uuid.UUID,
    body: PermissionRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "agent_permissions")

    _validate_permission_request(body)

    perm = await permission_service.upsert_permission(
        db,
        org.id,
        agent_id,
        mode=body.mode,
        default_action=body.default_action,
        allowed_tools=body.allowed_tools,
        blocked_tools=body.blocked_tools,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="agent_permission.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="agent_permission",
        resource_id=str(agent_id),
        details={
            "mode": body.mode,
            "default_action": body.default_action,
            "allowed_tools_count": len(body.allowed_tools),
            "blocked_tools_count": len(body.blocked_tools),
        },
    )
    await db.commit()
    return PermissionResponse.model_validate(perm)


@router.delete(
    "/agents/{agent_id}/permissions",
    status_code=204,
)
async def delete_agent_permissions(
    agent_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    plan_service.require_feature(org, "agent_permissions")
    deleted = await permission_service.delete_permission(db, org.id, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No permission record for this agent")
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="agent_permission.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="agent_permission",
        resource_id=str(agent_id),
    )
    await db.commit()


# ── Org-wide default ────────────────────────────────────────────


@router.get(
    "/permissions/default",
    response_model=PermissionResponse | None,
)
async def get_default_permissions(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse | None:
    org, _ = org_actor
    plan_service.require_feature(org, "agent_permissions")
    perm = await permission_service.get_permission(db, org.id, None)
    if perm is None:
        return None
    return PermissionResponse.model_validate(perm)


@router.put(
    "/permissions/default",
    response_model=PermissionResponse,
)
async def set_default_permissions(
    body: PermissionRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "agent_permissions")

    _validate_permission_request(body)

    perm = await permission_service.upsert_permission(
        db,
        org.id,
        None,
        mode=body.mode,
        default_action=body.default_action,
        allowed_tools=body.allowed_tools,
        blocked_tools=body.blocked_tools,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="default_permission.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="agent_permission",
        resource_id="org_default",
        details={
            "mode": body.mode,
            "default_action": body.default_action,
        },
    )
    await db.commit()
    return PermissionResponse.model_validate(perm)


# ── Validation ──────────────────────────────────────────────────


def _validate_permission_request(body: PermissionRequest) -> None:
    if body.mode not in ("enforcing", "dry_run", "disabled"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {body.mode}. Must be enforcing, dry_run, or disabled.",
        )
    if body.default_action not in ("allow", "deny"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid default_action: {body.default_action}. Must be allow or deny.",
        )
    if body.default_action == "deny" and not body.allowed_tools:
        raise HTTPException(
            status_code=400,
            detail="deny-by-default requires at least one tool in allowed_tools.",
        )
