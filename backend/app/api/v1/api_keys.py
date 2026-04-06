import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.db.models import Org
from app.db.session import get_db
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from app.services import api_key_service, audit_service

router = APIRouter()


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyResponse]:
    keys = await api_key_service.list_api_keys(db, org.id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreatedResponse:
    org, actor = org_actor
    api_key, raw_key = await api_key_service.create_api_key(db, org.id, body.name)
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="api_key.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="api_key",
        resource_id=str(api_key.id),
        details={"name": body.name, "key_prefix": api_key.key_prefix},
    )
    await db.commit()
    resp = ApiKeyCreatedResponse.model_validate(api_key)
    resp.raw_key = raw_key
    return resp


@router.delete("/{key_id}", response_model=ApiKeyResponse)
async def revoke_api_key(
    key_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    org, actor = org_actor
    api_key = await api_key_service.revoke_api_key(db, org.id, key_id)
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="api_key.revoked",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="api_key",
        resource_id=str(key_id),
        details={"name": api_key.name, "key_prefix": api_key.key_prefix},
    )
    await db.commit()
    return ApiKeyResponse.model_validate(api_key)
