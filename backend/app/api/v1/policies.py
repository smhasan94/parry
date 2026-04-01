import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_org
from app.db.models import Org
from app.db.session import get_db
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.services import policy_service

router = APIRouter()


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
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    policy = await policy_service.create_policy(
        db,
        org_id=org.id,
        **body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return PolicyResponse.model_validate(policy)


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    policy = await policy_service.update_policy(
        db,
        org_id=org.id,
        policy_id=policy_id,
        **body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return PolicyResponse.model_validate(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    await policy_service.delete_policy(db, org.id, policy_id)
    await db.commit()
