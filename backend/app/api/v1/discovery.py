"""Shadow AI discovery routes.

The zero-integration front door: an org connects a read-only SSO token and
gets back the AI systems its people already authorized — no SDK, no code
in the agent path.
"""

from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.discovery.okta import (
    OktaDomainError,
    fetch_okta_apps_and_users,
    parse_okta_response,
)
from app.discovery.sso_probe import ProcessingResult, SSOProbeProcessor
from app.schemas.discovery import (
    ShadowAIResponse,
    ShadowSystemResponse,
    SSOIngestRequest,
    SSOSyncRequest,
    SSOSyncResponse,
)
from app.services import audit_service, discovery_service

log = structlog.get_logger()
router = APIRouter()


@router.get("/shadow", response_model=ShadowAIResponse)
async def list_shadow_ai(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> ShadowAIResponse:
    """AI systems discovered in the environment that no agent covers."""
    org, _ = org_actor
    systems = await discovery_service.list_shadow_systems(db, org_id=org.id, limit=limit)
    summary = await discovery_service.shadow_summary(db, org_id=org.id)
    return ShadowAIResponse(
        total=summary["total"],
        by_risk_level=summary["by_risk_level"],
        systems=[ShadowSystemResponse.model_validate(s) for s in systems],
    )


@router.post("/sso/ingest", response_model=SSOSyncResponse)
async def ingest_sso_events(
    payload: SSOIngestRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SSOSyncResponse:
    """Process SSO grant records the customer exported themselves."""
    org, actor = org_actor
    if not payload.events:
        raise HTTPException(
            status_code=400, detail={"detail": "events must not be empty", "code": "EMPTY_BATCH"}
        )

    processor = await SSOProbeProcessor.create(db)
    result = await processor.process(db=db, org_id=org.id, events=payload.events)
    await _log_sync(db, org, actor, source="ingest", result=result)
    return _to_response(result)


@router.post("/sso/sync", response_model=SSOSyncResponse)
async def sync_okta(
    payload: SSOSyncRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SSOSyncResponse:
    """Pull app assignments from Okta and reconcile them."""
    org, actor = org_actor
    try:
        raw = await fetch_okta_apps_and_users(
            okta_domain=payload.okta_domain, api_token=payload.api_token
        )
    except OktaDomainError as exc:
        # Bad caller input, or an upstream trying to redirect pagination
        # off the authorized host. Either way the request is at fault.
        log.warning("okta_domain_rejected", org_id=str(org.id), reason=str(exc))
        raise HTTPException(
            status_code=400,
            detail={"detail": str(exc), "code": "INVALID_OKTA_DOMAIN"},
        ) from exc
    except httpx.HTTPError as exc:
        # Never include the exception body — Okta echoes request context
        # that can contain the token.
        log.warning("okta_fetch_failed", org_id=str(org.id), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={
                "detail": "Could not reach Okta with those credentials",
                "code": "OKTA_UNREACHABLE",
            },
        ) from exc

    processor = await SSOProbeProcessor.create(db)
    result = await processor.process_events(db=db, org_id=org.id, events=parse_okta_response(raw))
    await _log_sync(db, org, actor, source="okta", result=result)
    return _to_response(result)


def _to_response(result: ProcessingResult) -> SSOSyncResponse:
    return SSOSyncResponse(
        processed=result.processed,
        created=result.created,
        deduplicated=result.deduplicated,
        matched=result.matched,
        unmatched=result.unmatched,
    )


async def _log_sync(
    db: AsyncSession, org: Org, actor: Actor, *, source: str, result: ProcessingResult
) -> None:
    await audit_service.log_action(
        db,
        org.id,
        "discovery.sso_sync",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="probe",
        details={
            "source": source,
            "processed": result.processed,
            "created": result.created,
            "matched": result.matched,
        },
        obligation_ids=["art_26_1_deployer_register"],
    )
