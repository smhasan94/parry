"""Shadow AI discovery routes.

The zero-integration front door: an org connects a read-only SSO token and
gets back the AI systems its people already authorized — no SDK, no code
in the agent path.
"""

from __future__ import annotations

import uuid

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.exceptions import ConfigurationError
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
    ProbeCredentialCreate,
    ProbeCredentialResponse,
    ProbeCredentialRotate,
    ShadowAIResponse,
    ShadowSystemResponse,
    SSOIngestRequest,
    SSOSyncRequest,
    SSOSyncResponse,
)
from app.services import audit_service, discovery_service, probe_credential_service

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


# ── Probe Credentials ───────────────────────────────────────────


@router.post("/credentials", response_model=ProbeCredentialResponse, status_code=201)
async def create_credential(
    payload: ProbeCredentialCreate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ProbeCredentialResponse:
    """Store a credential so discovery can run on a schedule.

    The secret is encrypted before it reaches the database and is never
    returned by any endpoint.
    """
    org, actor = org_actor
    try:
        credential = await probe_credential_service.create(
            db,
            org_id=org.id,
            probe_type=payload.probe_type,
            provider=payload.provider,
            label=payload.label,
            secret=payload.secret,
            config=payload.config,
        )
    except ConfigurationError as exc:
        # The deployment is missing a key — an operator problem, not the
        # caller's, and not something to answer with a 500.
        log.error("probe_credential.unconfigured", org_id=str(org.id))
        raise HTTPException(
            status_code=503,
            detail={"detail": str(exc), "code": "CREDENTIAL_STORAGE_UNAVAILABLE"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"detail": str(exc), "code": "INVALID_CREDENTIAL"}
        ) from exc

    await audit_service.log_action(
        db,
        org.id,
        "probe_credential.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="probe_credential",
        resource_id=str(credential.id),
        details={"provider": payload.provider, "label": payload.label},
    )
    await db.commit()
    return ProbeCredentialResponse.model_validate(credential)


@router.get("/credentials", response_model=list[ProbeCredentialResponse])
async def list_credentials(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[ProbeCredentialResponse]:
    """Registered credentials, with their last sync outcome."""
    org, _ = org_actor
    credentials = await probe_credential_service.list_for_org(db, org_id=org.id)
    return [ProbeCredentialResponse.model_validate(c) for c in credentials]


@router.post("/credentials/{credential_id}/rotate", response_model=ProbeCredentialResponse)
async def rotate_credential(
    credential_id: uuid.UUID,
    payload: ProbeCredentialRotate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ProbeCredentialResponse:
    """Replace the stored token, e.g. after rotating it in Okta."""
    org, actor = org_actor
    credential = await probe_credential_service.rotate_secret(
        db, org_id=org.id, credential_id=credential_id, secret=payload.secret
    )
    await audit_service.log_action(
        db,
        org.id,
        "probe_credential.rotated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="probe_credential",
        resource_id=str(credential_id),
    )
    await db.commit()
    return ProbeCredentialResponse.model_validate(credential)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    await probe_credential_service.delete(db, org_id=org.id, credential_id=credential_id)
    await audit_service.log_action(
        db,
        org.id,
        "probe_credential.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="probe_credential",
        resource_id=str(credential_id),
    )
    await db.commit()
