"""WorkOS SSO adapter.

Layered alongside Clerk rather than replacing it — Clerk remains the
identity provider for every SaaS customer; WorkOS SSO exists only
for orgs that flip on SAML in their settings. When set,
``Org.workos_organization_id`` points at the matching WorkOS
organization and the routes under ``/api/v1/sso`` drive the SAML
flow.

The ``workos`` SDK is imported lazily so the backend boots without
the dep installed — missing SDK or empty credentials just means the
routes return 503. Every function takes an explicit ``client``
parameter so the unit tests can swap in a mock without touching the
real WorkOS API or needing the SDK at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.config import settings

log = structlog.get_logger()


class SSOError(Exception):
    """Raised for any SSO configuration or flow error — the routes
    surface these as 400/503 depending on cause."""


@dataclass(frozen=True)
class SSOProfile:
    """Flattened profile returned from a successful SAML exchange.

    This is the union of fields the dashboard needs after callback:
    enough identity to look up the user locally and enough metadata
    to audit-log the login. We never trust the email blindly — the
    org lookup goes through ``workos_organization_id`` first.
    """

    workos_user_id: str
    workos_organization_id: str | None
    email: str
    first_name: str | None
    last_name: str | None

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or self.email


# ── Client lazy-init ─────────────────────────────────────────────────


class _WorkOSClientProto(Protocol):
    """Shape of the bits of the WorkOS client we actually use.

    Kept as a Protocol so the mock we feed the unit tests doesn't have
    to inherit from the real SDK's class tree (which would drag in
    the workos package as a hard dep).
    """

    sso: Any
    portal: Any


def get_client() -> _WorkOSClientProto | None:
    """Return a configured WorkOS client, or ``None`` if unavailable.

    Returns ``None`` in three cases:

    * No ``workos_api_key`` / ``workos_client_id`` configured.
    * The ``workos`` package isn't installed.
    * Client construction raises (rare — surfaces in startup logs).

    Callers should treat ``None`` as "SSO not enabled on this
    backend" and respond with 503 to the client.
    """
    if not settings.workos_api_key or not settings.workos_client_id:
        return None
    try:
        from workos import WorkOSClient  # type: ignore[import-not-found]
    except ImportError:
        log.debug("sso.workos_sdk_missing")
        return None
    try:
        return WorkOSClient(  # type: ignore[no-any-return]
            api_key=settings.workos_api_key,
            client_id=settings.workos_client_id,
        )
    except Exception:  # pragma: no cover - surfaces via logs in startup
        log.warning("sso.client_init_failed", exc_info=True)
        return None


# ── Authorization URL ────────────────────────────────────────────────


def get_authorization_url(
    client: _WorkOSClientProto,
    *,
    organization_id: str,
    redirect_uri: str | None = None,
    state: str | None = None,
) -> str:
    """Start a SAML login for ``organization_id``.

    WorkOS returns an IdP-specific URL that the dashboard redirects
    the browser to. ``state`` is round-tripped to the callback so the
    caller can tie the redirect back to the original tab.
    """
    effective_redirect = redirect_uri or settings.workos_redirect_uri
    if not effective_redirect:
        raise SSOError("workos_redirect_uri is not configured")
    if not organization_id:
        raise SSOError("organization_id is required to start a SAML login")

    try:
        return client.sso.get_authorization_url(  # type: ignore[no-any-return]
            organization_id=organization_id,
            redirect_uri=effective_redirect,
            state=state,
        )
    except Exception as e:
        log.warning("sso.authorization_url_failed", error=str(e))
        raise SSOError(f"Failed to build SSO authorization URL: {e}") from e


# ── Callback exchange ────────────────────────────────────────────────


def _profile_from_workos(raw: Any) -> SSOProfile:
    """Normalise the WorkOS SDK's return value into ``SSOProfile``.

    Tolerant of both dict-shaped mocks (what the tests feed) and the
    SDK's attribute-shaped response objects. Raises ``SSOError`` if
    required fields are missing.
    """

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    profile_obj = _get(raw, "profile") or raw
    user_id = _get(profile_obj, "id")
    email = _get(profile_obj, "email")
    if not user_id or not email:
        raise SSOError("SSO callback response missing id or email")
    return SSOProfile(
        workos_user_id=str(user_id),
        workos_organization_id=(
            str(_get(profile_obj, "organization_id"))
            if _get(profile_obj, "organization_id")
            else None
        ),
        email=str(email),
        first_name=(
            str(_get(profile_obj, "first_name"))
            if _get(profile_obj, "first_name")
            else None
        ),
        last_name=(
            str(_get(profile_obj, "last_name"))
            if _get(profile_obj, "last_name")
            else None
        ),
    )


def exchange_code(client: _WorkOSClientProto, *, code: str) -> SSOProfile:
    """Exchange a WorkOS authorization code for a normalized profile."""
    if not code:
        raise SSOError("Missing authorization code")
    try:
        raw = client.sso.get_profile_and_token(code=code)
    except Exception as e:
        log.warning("sso.exchange_failed", error=str(e))
        raise SSOError(f"SSO code exchange failed: {e}") from e
    return _profile_from_workos(raw)


# ── Admin Portal ─────────────────────────────────────────────────────


def admin_portal_url(
    client: _WorkOSClientProto,
    *,
    organization_id: str,
    return_url: str | None = None,
    intent: str = "sso",
) -> str:
    """Generate a WorkOS AdminPortal link for a customer to configure
    their IdP without Parry touching their SAML metadata directly.

    ``intent`` defaults to ``"sso"`` which opens the SSO setup page;
    customers can be sent to ``"dsync"`` if directory sync is added
    later without touching this helper.
    """
    if not organization_id:
        raise SSOError("organization_id is required for AdminPortal link")
    try:
        return client.portal.generate_link(  # type: ignore[no-any-return]
            organization=organization_id,
            intent=intent,
            return_url=return_url,
        )
    except Exception as e:
        log.warning("sso.admin_portal_failed", error=str(e))
        raise SSOError(f"Failed to generate AdminPortal link: {e}") from e
