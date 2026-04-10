"""Customer-managed webhook endpoint CRUD + delivery history + test."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, plan_service, webhook_dispatch_service

log = structlog.get_logger()
router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────


class EndpointCreateRequest(ParrySchema):
    url: str
    event_types: list[str] = []
    description: str | None = None


class EndpointUpdateRequest(ParrySchema):
    url: str | None = None
    event_types: list[str] | None = None
    description: str | None = None
    is_active: bool | None = None


class EndpointResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    url: str
    secret: str
    description: str | None
    event_types: list[str]
    is_active: bool
    failure_count: int
    last_triggered_at: str | None
    created_at: str
    updated_at: str


class DeliveryResponse(ParrySchema):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_type: str
    payload: dict
    status_code: int | None
    response_body: str | None
    error: str | None
    attempt: int
    delivered_at: str


# ── Endpoint CRUD ───────────────────────────────────────────────


@router.get(
    "",
    response_model=list[EndpointResponse],
)
async def list_endpoints(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[EndpointResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")
    endpoints = await webhook_dispatch_service.list_endpoints(db, org.id)
    return [EndpointResponse.model_validate(e) for e in endpoints]


@router.post(
    "",
    response_model=EndpointResponse,
    status_code=201,
)
async def create_endpoint(
    body: EndpointCreateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> EndpointResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")

    # Validate event types
    invalid = set(body.event_types) - webhook_dispatch_service.VALID_EVENT_TYPES
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event types: {', '.join(invalid)}",
        )

    endpoint = await webhook_dispatch_service.create_endpoint(
        db, org.id, url=body.url, event_types=body.event_types,
        description=body.description,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="webhook.endpoint_created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint.id),
        details={"url": body.url, "event_types": body.event_types},
    )
    await db.commit()
    return EndpointResponse.model_validate(endpoint)


@router.patch(
    "/{endpoint_id}",
    response_model=EndpointResponse,
)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    body: EndpointUpdateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> EndpointResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")

    if body.event_types is not None:
        invalid = set(body.event_types) - webhook_dispatch_service.VALID_EVENT_TYPES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event types: {', '.join(invalid)}",
            )

    endpoint = await webhook_dispatch_service.update_endpoint(
        db, org.id, endpoint_id, **body.model_dump(exclude_unset=True),
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="webhook.endpoint_updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint_id),
    )
    await db.commit()
    return EndpointResponse.model_validate(endpoint)


@router.delete(
    "/{endpoint_id}",
    status_code=204,
)
async def delete_endpoint(
    endpoint_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")
    deleted = await webhook_dispatch_service.delete_endpoint(db, org.id, endpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="webhook.endpoint_deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint_id),
    )
    await db.commit()


# ── Delivery history ────────────────────────────────────────────


@router.get(
    "/{endpoint_id}/deliveries",
    response_model=list[DeliveryResponse],
)
async def list_deliveries(
    endpoint_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[DeliveryResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")
    # Verify endpoint belongs to org
    endpoint = await webhook_dispatch_service.get_endpoint(db, org.id, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    deliveries = await webhook_dispatch_service.list_deliveries(db, endpoint_id, limit)
    return [DeliveryResponse.model_validate(d) for d in deliveries]


# ── Test delivery ───────────────────────────────────────────────


@router.post(
    "/{endpoint_id}/test",
    response_model=dict,
)
async def test_endpoint(
    endpoint_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org, _ = org_actor
    plan_service.require_feature(org, "webhook_subscriptions")
    endpoint = await webhook_dispatch_service.get_endpoint(db, org.id, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    from app.workers.webhook_delivery_task import deliver_webhook
    import json

    test_payload = {
        "test": True,
        "message": "This is a test webhook from Parry",
        "org_id": str(org.id),
    }
    try:
        deliver_webhook.delay(
            str(endpoint_id),
            "test",
            json.dumps(test_payload),
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to enqueue test delivery")

    return {"status": "test_enqueued", "endpoint_id": str(endpoint_id)}
