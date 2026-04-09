import hashlib
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.services import audit_service, policy_regression_service, policy_service

router = APIRouter()


class SimulatePolicyRequest(ParrySchema):
    policy: dict[str, Any]
    days_back: int = 30
    sample_limit: int = 10


class SimulatePolicyResponse(ParrySchema):
    days_checked: int
    total_events_checked: int
    matched_count: int
    match_rate: float
    by_agent: dict[str, int]
    by_day: dict[str, int]
    samples: list[dict[str, Any]]
    truncated: bool
    pattern_is_valid: bool
    error: str | None = None


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


@router.get(
    "",
    response_model=list[PolicyResponse],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_policies(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[PolicyResponse]:
    policies = await policy_service.list_policies(db, org.id)
    return [PolicyResponse.model_validate(p) for p in policies]


@router.get(
    "/{policy_id}",
    response_model=PolicyResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_policy(
    policy_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    policy = await policy_service.get_policy(db, org.id, policy_id)
    return PolicyResponse.model_validate(policy)


@router.post(
    "",
    response_model=PolicyResponse,
    status_code=201,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
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


@router.patch(
    "/{policy_id}",
    response_model=PolicyResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
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


@router.delete(
    "/{policy_id}",
    status_code=204,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
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


@router.post("/simulate", response_model=SimulatePolicyResponse)
async def simulate_policy(
    body: SimulatePolicyRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SimulatePolicyResponse:
    """Run a candidate policy against the org's recent events.

    Read-only — does NOT persist anything to the policies table or
    create Detection rows. Lets admins preview the impact of adding
    a blocked tool, blocking a domain, or tightening a forbidden
    pattern before saving the policy. Audit-logged with a hash of
    the candidate policy keys (not values) to keep the trail compact.
    """
    org, actor = org_actor

    report = await policy_regression_service.simulate_policy(
        db,
        org.id,
        policy=body.policy,
        days_back=max(1, min(body.days_back, 90)),
        sample_limit=max(1, min(body.sample_limit, 50)),
    )

    policy_hash = hashlib.sha256(
        json.dumps(body.policy, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="policy.simulated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="policy",
        resource_id=policy_hash,
        details={
            "policy_hash": policy_hash,
            "policy_keys": sorted(body.policy.keys()),
            "days_back": body.days_back,
            "matched_count": report["matched_count"],
            "total_events_checked": report["total_events_checked"],
            "truncated": report["truncated"],
        },
    )
    await db.commit()
    return SimulatePolicyResponse(**report)
