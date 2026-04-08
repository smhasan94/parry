"""WorkOS SAML SSO routes.

Three endpoints:

* ``POST /api/v1/sso/login`` — start a SAML flow for a given
  customer slug or WorkOS organization id. Unauthenticated — anyone
  with the org slug can initiate, and WorkOS itself enforces the
  actual authentication.

* ``GET /api/v1/sso/callback`` — handle the WorkOS redirect,
  exchange the authorization code for a profile, look up the org,
  and hand back a profile payload the dashboard can use. **Session
  minting is out of scope** for this route — the dashboard is
  expected to bridge the profile into Clerk via a custom
  authentication token flow. The route explicitly returns the
  profile JSON rather than setting a cookie so the integration
  point is clearly visible.

* ``POST /api/v1/sso/admin-portal`` — owner-gated, generates a
  WorkOS AdminPortal link so the customer can configure their IdP
  SAML metadata without Parry touching it directly.

When the WorkOS SDK isn't installed or credentials are empty,
``sso_service.get_client()`` returns None and every route responds
503 "SSO not configured on this backend".
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, sso_service
from app.services.sso_service import SSOError

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class LoginRequest(ParrySchema):
    """Start-SAML request. Either an ``org_slug`` (clerk_org_id) or an
    explicit ``workos_organization_id`` is accepted. Slug lookups let
    the dashboard drive the flow without knowing WorkOS ids."""

    org_slug: str | None = None
    workos_organization_id: str | None = None
    state: str | None = None
    redirect_uri: HttpUrl | None = None


class LoginResponse(ParrySchema):
    authorization_url: str


class CallbackResponse(ParrySchema):
    org_id: str
    org_name: str
    workos_user_id: str
    workos_organization_id: str | None
    email: str
    display_name: str


class AdminPortalRequest(ParrySchema):
    return_url: HttpUrl | None = None


class AdminPortalResponse(ParrySchema):
    url: str


# ── Helpers ──────────────────────────────────────────────────────────


def _require_client() -> sso_service._WorkOSClientProto:
    client = sso_service.get_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO is not configured on this backend.",
        )
    return client


async def _resolve_workos_org_id(
    db: AsyncSession, body: LoginRequest
) -> tuple[str, Org]:
    """Resolve the target WorkOS organization id from the request.

    Returns ``(workos_organization_id, parry_org)``. Raises 400 when
    neither field is present and 404 when the slug doesn't map to a
    known org or the org has no WorkOS id configured.
    """
    if body.workos_organization_id:
        result = await db.execute(
            select(Org).where(
                Org.workos_organization_id == body.workos_organization_id
            )
        )
        org = result.scalar_one_or_none()
        if org is None:
            raise HTTPException(
                status_code=404, detail="No Parry org matches that WorkOS id"
            )
        return body.workos_organization_id, org

    if body.org_slug:
        result = await db.execute(
            select(Org).where(Org.clerk_org_id == body.org_slug)
        )
        org = result.scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=404, detail="Org not found")
        if not org.workos_organization_id:
            raise HTTPException(
                status_code=400,
                detail="SSO is not enabled for this organization.",
            )
        return org.workos_organization_id, org

    raise HTTPException(
        status_code=400,
        detail="Either org_slug or workos_organization_id is required.",
    )


# ── Routes ──────────────────────────────────────────────────────────


class SSOStatusResponse(ParrySchema):
    """Tiny status surface for the dashboard's Settings SSO card."""

    enabled: bool
    configured_on_backend: bool
    workos_organization_id: str | None


@router.get(
    "/status",
    response_model=SSOStatusResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def sso_status(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
) -> SSOStatusResponse:
    """Return whether SAML SSO is enabled for the caller's org.

    Split into two booleans:

    * ``configured_on_backend`` — do we have WorkOS credentials at
      all? When false the whole feature is off for every org.
    * ``enabled`` — is this specific org configured with a WorkOS
      organization id? Independent of the backend config, so the UI
      can show "contact us to enable" vs "SSO is configured" vs
      "SSO feature unavailable on this deployment".
    """
    org, _actor = org_actor
    return SSOStatusResponse(
        enabled=bool(org.workos_organization_id),
        configured_on_backend=sso_service.get_client() is not None,
        workos_organization_id=org.workos_organization_id,
    )


@router.post("/login", response_model=LoginResponse)
async def sso_login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Start a SAML flow for the requested organization."""
    client = _require_client()
    workos_org_id, _org = await _resolve_workos_org_id(db, body)

    try:
        url = sso_service.get_authorization_url(
            client,
            organization_id=workos_org_id,
            redirect_uri=str(body.redirect_uri) if body.redirect_uri else None,
            state=body.state,
        )
    except SSOError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return LoginResponse(authorization_url=url)


@router.get("/callback", response_model=CallbackResponse)
async def sso_callback(
    code: str = Query(..., description="Authorization code from WorkOS"),
    db: AsyncSession = Depends(get_db),
) -> CallbackResponse:
    """Exchange a WorkOS authorization code for a profile + org lookup.

    This route intentionally does not mint a session cookie. The
    dashboard bridges the returned profile into its own session (via
    Clerk's custom token flow) — keeping session minting out of the
    backend means there's exactly one place in the system that owns
    auth state (Clerk), and SSO is a layer on top rather than a
    parallel identity store.
    """
    client = _require_client()

    try:
        profile = sso_service.exchange_code(client, code=code)
    except SSOError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    org: Org | None = None
    if profile.workos_organization_id:
        result = await db.execute(
            select(Org).where(
                Org.workos_organization_id == profile.workos_organization_id
            )
        )
        org = result.scalar_one_or_none()

    if org is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "SSO succeeded but no Parry org matches the WorkOS "
                "organization id. Ask an owner to configure SSO for "
                "this organization in Parry settings."
            ),
        )

    # Audit-log the login as a system-actor entry so there's a
    # tamper-evident record of who came in via SSO even before the
    # dashboard mints a local session.
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="sso.login_completed",
        actor_type="system",
        actor_id=profile.workos_user_id,
        actor_label=profile.email,
        resource_type="sso",
        resource_id=profile.workos_organization_id,
        details={
            "workos_user_id": profile.workos_user_id,
            "email": profile.email,
        },
    )
    await db.commit()

    log.info(
        "sso.login_completed",
        org_id=str(org.id),
        email=profile.email,
    )

    return CallbackResponse(
        org_id=str(org.id),
        org_name=org.name,
        workos_user_id=profile.workos_user_id,
        workos_organization_id=profile.workos_organization_id,
        email=profile.email,
        display_name=profile.display_name,
    )


@router.post(
    "/admin-portal",
    response_model=AdminPortalResponse,
    dependencies=[Depends(require_role(Role.OWNER))],
)
async def generate_admin_portal(
    body: AdminPortalRequest,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AdminPortalResponse:
    """Generate a WorkOS AdminPortal link for the caller's org.

    Requires owner role — an admin configuring IdP metadata is
    effectively changing who can access the account, so we treat it
    the same as billing controls.
    """
    client = _require_client()
    org, actor = org_actor

    if not org.workos_organization_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "This org has no WorkOS organization id configured. "
                "Contact Parry to enable SAML SSO."
            ),
        )

    try:
        url = sso_service.admin_portal_url(
            client,
            organization_id=org.workos_organization_id,
            return_url=str(body.return_url) if body.return_url else None,
        )
    except SSOError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="sso.admin_portal_generated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="sso",
        resource_id=org.workos_organization_id,
    )
    await db.commit()

    return AdminPortalResponse(url=url)
