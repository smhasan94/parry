import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import Org
from app.db.session import get_db
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.services import audit_service, policy_service

router = APIRouter()


def _policy_summary(policy) -> dict:
    """Compact view of a policy for audit log details."""
    return {
        "name": policy.name,
        "is_active": policy.is_active,
        "allowed_tools": policy.allowed_tools or [],
        "blocked_tools": policy.blocked_tools or [],
        "max_token_budget": policy.max_token_budget,
        "forbidden_patterns": policy.forbidden_patterns or [],
    }


@router.get("", response_model=list[PolicyResponse])
async def list_policies(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[PolicyResponse]:
    policies = await policy_service.list_policies(db, org.id)
    return [PolicyResponse.model_validate(p) for p in policies]


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    policy = await policy_service.get_policy(db, org.id, policy_id)
    return PolicyResponse.model_validate(policy)


@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    body: PolicyCreate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    org, actor = org_actor
    policy = await policy_service.create_policy(
        db,
        org_id=org.id,
        **body.model_dump(exclude_unset=True),
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="policy.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="policy",
        resource_id=str(policy.id),
        details=_policy_summary(policy),
    )
    await db.commit()
    return PolicyResponse.model_validate(policy)


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    org, actor = org_actor

    # Snapshot the previous state for the audit diff
    previous = await policy_service.get_policy(db, org.id, policy_id)
    before = _policy_summary(previous)

    policy = await policy_service.update_policy(
        db,
        org_id=org.id,
        policy_id=policy_id,
        **body.model_dump(exclude_unset=True),
    )
    after = _policy_summary(policy)

    # Only log fields that actually changed
    changes = {k: {"before": before[k], "after": after[k]} for k in after if before[k] != after[k]}
    if changes:
        await audit_service.log_action(
            db,
            org_id=org.id,
            action="policy.updated",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_label=actor.label,
            resource_type="policy",
            resource_id=str(policy_id),
            details={"name": policy.name, "changes": changes},
        )

    await db.commit()
    return PolicyResponse.model_validate(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    # Capture the policy state before deletion for the audit record
    deleted = await policy_service.get_policy(db, org.id, policy_id)
    snapshot = _policy_summary(deleted)
    await policy_service.delete_policy(db, org.id, policy_id)
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="policy.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="policy",
        resource_id=str(policy_id),
        details=snapshot,
    )
    await db.commit()
