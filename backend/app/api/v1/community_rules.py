"""Community detection rule pack marketplace API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, community_rules_service

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────

class RuleSchema(ParrySchema):
    name: str
    pattern: str
    target: Literal["prompt", "response", "both"] = "both"
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class PackCreate(ParrySchema):
    name: str
    description: str | None = None
    category: str
    rules: list[RuleSchema]


class PackUpdate(ParrySchema):
    rules: list[RuleSchema]


class PackResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    category: str
    rules: list[dict[str, Any]]
    version: int
    install_count: int
    is_public: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    pack_id: uuid.UUID
    installed_version: int
    created_at: datetime
    pack: PackResponse | None = None


# ── Public browsing ─────────────────────────────────────────────────

@router.get("/packs", response_model=list[PackResponse])
async def list_packs(
    category: str | None = None,
    search: str | None = None,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[PackResponse]:
    packs = await community_rules_service.list_packs(db, category=category, search=search)
    return [PackResponse.model_validate(p, from_attributes=True) for p in packs]


@router.get("/packs/{pack_id}", response_model=PackResponse)
async def get_pack(
    pack_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PackResponse:
    pack = await community_rules_service.get_pack(db, pack_id)
    return PackResponse.model_validate(pack, from_attributes=True)


@router.get("/categories")
async def list_categories(
    org: Org = Depends(get_current_org),
) -> list[str]:
    return community_rules_service.VALID_CATEGORIES


# ── Publishing ──────────────────────────────────────────────────────

@router.post(
    "/packs",
    response_model=PackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def publish_pack(
    body: PackCreate,
    org: Org = Depends(get_current_org),
    actor: Actor = Depends(),
    db: AsyncSession = Depends(get_db),
) -> PackResponse:
    try:
        pack = await community_rules_service.publish_pack(
            db,
            org_id=org.id,
            name=body.name,
            description=body.description,
            category=body.category,
            rules=[r.model_dump() for r in body.rules],
        )
        await db.flush()
        await audit_service.log_action(
            db,
            org_id=org.id,
            actor_id=actor.clerk_user_id,
            action="community_pack.published",
            resource_type="community_rule_pack",
            resource_id=str(pack.id),
            details={"name": pack.name, "rule_count": len(pack.rules)},
        )
        return PackResponse.model_validate(pack, from_attributes=True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.patch(
    "/packs/{pack_id}",
    response_model=PackResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_pack(
    pack_id: uuid.UUID,
    body: PackUpdate,
    org: Org = Depends(get_current_org),
    actor: Actor = Depends(),
    db: AsyncSession = Depends(get_db),
) -> PackResponse:
    try:
        pack = await community_rules_service.update_pack(
            db,
            pack_id=pack_id,
            org_id=org.id,
            rules=[r.model_dump() for r in body.rules],
        )
        await audit_service.log_action(
            db,
            org_id=org.id,
            actor_id=actor.clerk_user_id,
            action="community_pack.updated",
            resource_type="community_rule_pack",
            resource_id=str(pack.id),
            details={"version": pack.version},
        )
        return PackResponse.model_validate(pack, from_attributes=True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# ── Installation ────────────────────────────────────────────────────

@router.get("/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionResponse]:
    subs = await community_rules_service.list_subscriptions(db, org.id)
    return [SubscriptionResponse.model_validate(s, from_attributes=True) for s in subs]


@router.post(
    "/packs/{pack_id}/install",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def install_pack(
    pack_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    actor: Actor = Depends(),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    sub = await community_rules_service.install_pack(db, org_id=org.id, pack_id=pack_id)
    await db.flush()
    await audit_service.log_action(
        db,
        org_id=org.id,
        actor_id=actor.clerk_user_id,
        action="community_pack.installed",
        resource_type="community_rule_pack",
        resource_id=str(pack_id),
    )
    return SubscriptionResponse.model_validate(sub, from_attributes=True)


@router.delete(
    "/packs/{pack_id}/uninstall",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def uninstall_pack(
    pack_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    actor: Actor = Depends(),
    db: AsyncSession = Depends(get_db),
) -> None:
    await community_rules_service.uninstall_pack(db, org_id=org.id, pack_id=pack_id)
    await audit_service.log_action(
        db,
        org_id=org.id,
        actor_id=actor.clerk_user_id,
        action="community_pack.uninstalled",
        resource_type="community_rule_pack",
        resource_id=str(pack_id),
    )


@router.get("/published", response_model=list[PackResponse])
async def list_published(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[PackResponse]:
    """List packs published by the current org."""
    packs = await community_rules_service.list_published(db, org.id)
    return [PackResponse.model_validate(p, from_attributes=True) for p in packs]
