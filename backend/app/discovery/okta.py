"""Okta SSO probe client.

Reads the app assignments an org has already granted. Requires one
read-only API token — no code in the customer's agent path, which is why
this is the cheapest discovery surface to get a prospect to turn on.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import structlog

from app.discovery.events import NormalizedSSOEvent

log = structlog.get_logger()

_STATUS_MAP = {"ACTIVE": "active", "INACTIVE": "inactive"}

# Okta tenants are a single label under one of these apexes. Anchored, so
# "acme.okta.com.evil.test" and "acme.okta.com@evil.test" both fail.
_OKTA_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.okta(?:preview|-emea)?\.com$")


class OktaDomainError(ValueError):
    """The supplied Okta host is not a valid, allowlisted Okta tenant."""


def resolve_base_url(okta_domain: str) -> str:
    """Validate a caller-supplied Okta host and build its base URL.

    ``okta_domain`` reaches us in a request body and the resulting URL is
    fetched server-side with an Authorization header. Without an allowlist
    a customer admin could aim Parry's outbound request at link-local
    metadata or anything else inside our own network, so parse the host
    rather than trusting the string, and reject any userinfo, port, path,
    query, or fragment smuggled alongside it.
    """
    candidate = (okta_domain or "").strip().lower()
    if not candidate:
        raise OktaDomainError("okta_domain must not be empty")

    # urlsplit only populates hostname/port/path when a scheme is present.
    parts = urlsplit(f"//{candidate}", scheme="https")
    if parts.path or parts.query or parts.fragment:
        raise OktaDomainError(f"okta_domain must be a bare hostname, got {okta_domain!r}")
    if parts.username or parts.password:
        raise OktaDomainError("okta_domain must not contain credentials")
    try:
        if parts.port is not None:
            raise OktaDomainError("okta_domain must not specify a port")
    except ValueError as exc:  # malformed port, e.g. "host:notaport"
        raise OktaDomainError("okta_domain has an invalid port") from exc

    host = parts.hostname or ""
    if not _OKTA_HOST.match(host):
        raise OktaDomainError(f"{okta_domain!r} is not a recognized Okta tenant domain")

    return f"https://{host}"


def validate_next_url(url: str | None, expected_host: str) -> str | None:
    """Guard the pagination cursor.

    The next-page URL comes from the upstream's Link header, so it is not
    ours to trust: an upstream that answers as Okta could hand back a
    link-local address and we would follow it with the token attached.
    Every hop must stay on the host the caller authorized, over TLS.
    """
    if not url:
        return None

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise OktaDomainError(f"pagination link must use https, got {parts.scheme!r}")
    if (parts.hostname or "").lower() != expected_host.lower():
        raise OktaDomainError(f"pagination link left the authorized host {expected_host!r}")
    return url


def _parse_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=UTC)


def parse_okta_response(okta_data: list[dict]) -> list[NormalizedSSOEvent]:
    """Flatten Okta's app-with-assignments payload into one event per
    (app, user), or a single unassigned event for apps with no users."""
    events: list[NormalizedSSOEvent] = []

    for item in okta_data:
        app = item.get("app")
        if not app:
            log.warning("okta_entry_missing_app", keys=sorted(item))
            continue

        users = item.get("users") or []
        # An app with no assignments still counts as discovered — it was
        # provisioned, which is the signal. Represent it as one event
        # with no user attached.
        logins = [u.get("profile", {}).get("login") for u in users] or [None]

        events.extend(
            NormalizedSSOEvent(
                timestamp=_parse_timestamp(app.get("created", "")),
                provider="okta",
                oauth_app_id=app.get("id"),
                app_name=app.get("label", "Unknown"),
                user_identifier=login,
                grant_type="admin_assigned",
                status=_STATUS_MAP.get(app.get("status", ""), "unknown"),
                raw=item,
            )
            for login in logins
        )

    return events


async def fetch_okta_apps_and_users(*, okta_domain: str, api_token: str) -> list[dict]:
    """Page through /api/v1/apps and each app's assignments.

    Raises ``OktaDomainError`` for a host outside the Okta allowlist, or
    if the upstream tries to steer pagination off that host.
    """
    base_url = resolve_base_url(okta_domain)
    host = urlsplit(base_url).hostname or ""
    headers = {"Authorization": f"SSWS {api_token}", "Accept": "application/json"}
    results: list[dict] = []

    # follow_redirects is off by default in httpx; pinned explicitly so a
    # 302 can never relay the Authorization header to another host.
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=False) as client:
        url: str | None = f"{base_url}/api/v1/apps"
        while url:
            resp = await client.get(url)
            resp.raise_for_status()
            for app in resp.json():
                results.append(
                    {"app": app, "users": await _fetch_users(client, base_url, host, app)}
                )
            url = _next_url(resp, host)

    log.info("okta_fetch_complete", app_count=len(results))
    return results


async def _fetch_users(
    client: httpx.AsyncClient, base_url: str, host: str, app: dict
) -> list[dict]:
    users: list[dict] = []
    url: str | None = f"{base_url}/api/v1/apps/{app['id']}/users"
    while url:
        resp = await client.get(url)
        resp.raise_for_status()
        users.extend(resp.json())
        url = _next_url(resp, host)
    return users


def _next_url(resp: httpx.Response, host: str) -> str | None:
    return validate_next_url(resp.links.get("next", {}).get("url"), host)
