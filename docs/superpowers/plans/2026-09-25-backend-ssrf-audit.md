# Backend SSRF Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the SSRF gap in every backend code path that fetches a customer-supplied URL server-side (webhook endpoints, alert integrations), using the same address-based reasoning the SDK's MCP validator (`sdk/parry/mcp/validate.py`) already applies.

**Architecture:** One new pure-function validator (`app/core/url_safety.py`) ported from the SDK's address logic (loopback/link-local/reserved/private/CGNAT checks decided positively on `is_global`, plus IPv6-embedded-v4 unwrapping), wired into every write path that stores a customer URL and every send path that dials one.

**Tech Stack:** Python 3.12, `ipaddress` stdlib, FastAPI exception handlers, httpx, pytest + pytest-asyncio.

**Spec:** No separate spec doc exists for this item — the Problem Statement below stands in for one; it was derived by reading the actual code, not carried over from a prior design doc.

## Problem Statement

The Okta discovery client (`backend/app/discovery/okta.py`, tested by `backend/tests/discovery/test_okta_ssrf.py`) is **not** a gap. It defends with a domain allowlist (`_OKTA_HOST` anchored to `*.okta.com` / `*.oktapreview.com` / `*.okta-emea.com`) rather than address inspection — and that is the right defense for it, because the attacker (a customer admin) does not control DNS for `okta.com`. The three address-form bugs the SDK fix closed (unresolved hostnames, `::1` loopback misclassified as merely "reserved", CGNAT `100.64.0.0/10` reading as `is_private=False`) are irrelevant to a validator that never inspects a resolved address at all. No task in this plan touches `okta.py`.

The real, previously unaudited gap is different and worse: two other backend paths fetch a **fully customer-controlled URL**, with **zero** validation of any kind — not even a domain allowlist:

1. **Webhook endpoints** (`backend/app/api/v1/webhook_endpoints.py` → `webhook_dispatch_service.create_endpoint`/`update_endpoint` → `backend/app/workers/webhook_delivery_task.py`). An org ADMIN sets `WebhookEndpoint.url` (`Text`, unvalidated) via `POST/PATCH /api/v1/webhooks/endpoints`, and the Celery task `deliver_webhook` later POSTs an HMAC-signed payload to that exact string with no address check. `POST .../test` lets the admin trigger this immediately.
2. **Alert config** (`backend/app/api/v1/alerts.py` `update_alert_config` → `backend/app/services/alert_service.py` `send_slack_alert`/`send_webhook_alert`). `slack_webhook_url` and `webhook_url` are typed as Pydantic `HttpUrl` — syntactic validation only, no address check — and later POSTed to directly.

Both are a stored SSRF: a customer admin can point either URL at `169.254.169.254` (cloud metadata) or an internal service, and the backend will dial it with its own network position, on a repeating schedule (webhooks fire per event; alerts fire per incident).

Not in scope, and why: `send_pagerduty_alert` posts to a hardcoded `https://events.pagerduty.com/v2/enqueue`; `send_opsgenie_alert` posts to a hardcoded `https://api.opsgenie.com/v2/alerts`. Neither takes a customer-supplied host, so there is nothing to validate.

## Global Constraints

- New validator lives at `backend/app/core/url_safety.py` and must not import from `sdk/` — the backend has no dependency on the SDK package today and this plan does not add one. Port the address logic; do not import it.
- The validator enforces **https-only, no `allow_private` escape hatch**. Every URL this plan touches is a customer-configured *outbound notification target* (webhook receiver, Slack incoming webhook, generic alert webhook) — there is no legitimate case for a private or plaintext target, unlike the SDK's MCP client which has a real "internal MCP server" deployment shape. Do not add an opt-out flag.
- Raising `UnsafeURLError` at write time (create/update) must produce `400`. Raising it at send time (delivery/alert dispatch) must be caught and folded into that path's existing failure handling — never let it escape as an unhandled exception or change an existing function's return-value contract (`send_slack_alert`/`send_webhook_alert` already return `bool`; keep that).
- Follow existing repo conventions: `ParryError` subclass + `app.exception_handler` registration in `main.py` (see `NotFoundError`/`ConflictError`/`PolicyViolationError` for the pattern), not ad hoc `HTTPException` raises inside services.
- Every test that checks an address-form rule (private/reserved/CGNAT/embedded-v4) uses a **literal IP in the URL**, not a hostname needing DNS resolution — `ipaddress.ip_address()` accepts a literal directly, so these tests need no resolver injection and no network access.

## Review Focus

- **Update, not just create, must be checked.** `webhook_dispatch_service.update_endpoint` takes `**updates` generically; a task that only guards `create_endpoint` leaves `PATCH /endpoints/{id}` open to swap a safe URL for `169.254.169.254` after creation. Task 2 covers both.
- **Revalidation at send time, not just at write time.** A URL that resolved safely at creation can be repointed by its operator's DNS before the next delivery (the same TOCTOU class the SDK's docstring calls out as an accepted, unclosed gap for the MCP client — here it's closable cheaply because delivery already re-reads the row). Tasks 3 and 5 revalidate immediately before each outbound call.
- **Embedded-v4 IPv6 forms must be checked, not just plain private/loopback ranges.** A URL like `https://[64:ff9b::a9fe:a9fe]/hook` (NAT64-embedded metadata IP) must be refused by the same logic that refused it in the SDK client — Task 1's unit tests pin this, not just `169.254.169.254` directly.
- **The `code` field in the 400 response must be stable and specific** (`UNSAFE_URL`), not a generic validation-error shape, so the dashboard can show a distinct message rather than a generic "bad request."
- **Failure must not silently pass.** `send_webhook_alert`/`send_slack_alert` return `False` today on `httpx.HTTPError`; a validation failure must land in that same `False` + logged-warning path, not raise past `dispatch_incident_alert` and abort every other configured channel for the incident.

---

## File Structure

- Create: `backend/app/core/url_safety.py` — `UnsafeURLError` + `assert_public_https_url(url, *, resolver=None)`. Pure, no DB, no framework imports beyond `app.core.exceptions.ParryError`.
- Create: `backend/tests/test_url_safety.py` — unit tests for the validator alone.
- Modify: `backend/app/main.py` — register the `UnsafeURLError` → `400` exception handler.
- Modify: `backend/app/services/webhook_dispatch_service.py` — validate `url` in `create_endpoint` and `update_endpoint`.
- Modify: `backend/app/workers/webhook_delivery_task.py` — revalidate `endpoint.url` in `_deliver` immediately before the HTTP call.
- Modify: `backend/app/api/v1/alerts.py` — validate `slack_webhook_url`/`webhook_url` in `update_alert_config`.
- Modify: `backend/app/services/alert_service.py` — revalidate the URL in `send_slack_alert` and `send_webhook_alert` immediately before the HTTP call.
- Create: `backend/tests/e2e/test_webhook_endpoint_ssrf.py` — router-level create/update rejection + accept tests.
- Create: `backend/tests/e2e/test_webhook_delivery_ssrf.py` — delivery-time revalidation test (bypasses the service layer to insert an unsafe URL directly, proving the send-time check is independent of the write-time one).
- Create: `backend/tests/e2e/test_alert_config_ssrf.py` — router-level `update_alert_config` rejection test.
- Create: `backend/tests/test_alert_service_ssrf.py` — pure unit tests for `send_slack_alert`/`send_webhook_alert` revalidation (no DB needed — these functions take a URL and an `Incident` object directly).

---

### Task 1: The validator

**Files:**
- Create: `backend/app/core/url_safety.py`
- Test: `backend/tests/test_url_safety.py`

**Interfaces:**
- Produces: `UnsafeURLError(ParryError)` (code `"UNSAFE_URL"`); `Resolver = Callable[[str], list[str]]`; `assert_public_https_url(url: str, *, resolver: Resolver | None = None) -> None` — raises `UnsafeURLError`, returns `None` on success.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_url_safety.py
"""Address-based SSRF checks for customer-supplied outbound URLs.

Mirrors sdk/tests/test_mcp_validate.py's approach: every test that
needs a hostname injects a resolver so the suite never touches the
network, and every address-form test uses a literal IP so it needs
no resolver at all.
"""

from __future__ import annotations

import pytest

from app.core.url_safety import Resolver, UnsafeURLError, assert_public_https_url


def resolves_to(*addresses: str) -> Resolver:
    return lambda host: list(addresses)


PUBLIC_IP = "93.184.216.34"
public = resolves_to(PUBLIC_IP)


class TestSchemeAndShape:
    def test_accepts_a_public_https_url(self) -> None:
        assert_public_https_url("https://example.com/hook", resolver=public)

    def test_rejects_http(self) -> None:
        with pytest.raises(UnsafeURLError, match="https"):
            assert_public_https_url("http://example.com/hook", resolver=public)

    def test_rejects_empty(self) -> None:
        with pytest.raises(UnsafeURLError):
            assert_public_https_url("", resolver=public)

    def test_rejects_embedded_credentials(self) -> None:
        with pytest.raises(UnsafeURLError, match="credentials"):
            assert_public_https_url("https://user:pass@example.com/hook", resolver=public)


class TestLiteralAddressesNeedNoResolver:
    def test_rejects_cloud_metadata_ip(self) -> None:
        with pytest.raises(UnsafeURLError, match="link-local"):
            assert_public_https_url("https://169.254.169.254/hook")

    def test_rejects_loopback(self) -> None:
        with pytest.raises(UnsafeURLError, match="loopback"):
            assert_public_https_url("https://127.0.0.1/hook")

    def test_rejects_ipv6_loopback(self) -> None:
        with pytest.raises(UnsafeURLError, match="loopback"):
            assert_public_https_url("https://[::1]/hook")

    def test_rejects_private_range(self) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            assert_public_https_url("https://10.0.0.5/hook")

    def test_rejects_cgnat_range(self) -> None:
        # 100.64.0.0/10 — is_private=False, is_reserved=False, is_global=False.
        # A deny-list would miss this; the is_global check does not.
        with pytest.raises(UnsafeURLError, match="globally routable"):
            assert_public_https_url("https://100.64.0.1/hook")

    def test_rejects_nat64_embedded_metadata_ip(self) -> None:
        # 64:ff9b::a9fe:a9fe carries 169.254.169.254 inside it.
        with pytest.raises(UnsafeURLError, match="link-local"):
            assert_public_https_url("https://[64:ff9b::a9fe:a9fe]/hook")

    def test_accepts_a_public_literal_ip(self) -> None:
        assert_public_https_url(f"https://{PUBLIC_IP}/hook")


class TestNamesAreJudgedByWhatTheyResolveTo:
    def test_name_pointing_at_metadata_is_refused(self) -> None:
        with pytest.raises(UnsafeURLError, match="link-local"):
            assert_public_https_url(
                "https://metadata-proxy.attacker.example/hook",
                resolver=resolves_to("169.254.169.254"),
            )

    def test_unresolvable_name_is_refused(self) -> None:
        def _fails(host: str) -> list[str]:
            raise OSError(f"no such host: {host}")

        with pytest.raises(UnsafeURLError, match="could not resolve"):
            assert_public_https_url("https://nowhere.example/hook", resolver=_fails)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_url_safety.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.url_safety'`

- [ ] **Step 3: Write the validator**

```python
# backend/app/core/url_safety.py
"""Decide whether a customer-supplied URL is safe for Parry's own
server to fetch or POST to.

Every caller here is the same shape: a customer admin configures a
URL (a webhook receiver, a Slack incoming webhook), and Parry's
backend — not the customer's network — is the one that dials it on a
schedule (per event, per incident). That is a stored SSRF if the URL
is not checked: an admin points it at 169.254.169.254 and Parry's own
process hands back cloud credentials, or points it at an internal
service Parry can reach but the admin's own network cannot.

Ported from sdk/parry/mcp/validate.py's address reasoning, which is
the reference implementation for this class of check in this
codebase — see that module's docstring for the full rationale on why
reachability is decided positively (an address must be is_global)
rather than by enumerating deny ranges, and why IPv6 forms that carry
an IPv4 address inside them (v4-mapped, 6to4, NAT64, Teredo) are
unwrapped and judged by what they route to.

Unlike the MCP client, there is no allow_private here: every caller
is an outbound notification target, and there is no legitimate case
for one of those to be private or plaintext.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from app.core.exceptions import ParryError

Resolver = Callable[[str], list[str]]
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_METADATA_HOSTS = {"metadata.google.internal", "metadata.goog", "instance-data"}
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


class UnsafeURLError(ParryError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="UNSAFE_URL")


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _embedded_v4(ip: _IPAddress) -> list[ipaddress.IPv4Address]:
    if not isinstance(ip, ipaddress.IPv6Address):
        return []
    found = [addr for addr in (ip.ipv4_mapped, ip.sixtofour) if addr is not None]
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in _NAT64_PREFIX:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF))
    return found


def _check_one(ip: _IPAddress, *, where: str) -> None:
    if ip.is_link_local:
        raise UnsafeURLError(
            f"refusing to reach {where}: link-local address "
            "(cloud metadata services live here)"
        )
    if ip.is_loopback:
        raise UnsafeURLError(f"refusing to reach {where}: loopback address")
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise UnsafeURLError(f"refusing to reach {where}: reserved address")
    if ip.is_private:
        raise UnsafeURLError(f"refusing to reach {where}: private address")
    if not ip.is_global:
        raise UnsafeURLError(f"refusing to reach {where}: not a globally routable address")


def _check_address(raw: str, *, host: str) -> None:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:  # pragma: no cover — getaddrinfo returns valid IPs
        return

    where = f"{host} ({raw})" if raw != host else host
    for candidate in (ip, *_embedded_v4(ip)):
        label = where if candidate is ip else f"{where} -> {candidate}"
        _check_one(candidate, where=label)


def _addresses_for(host: str, resolver: Resolver | None) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass

    resolve = resolver or _default_resolver
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise UnsafeURLError(f"could not resolve host {host!r}: {exc}") from exc
    if not addresses:
        raise UnsafeURLError(f"host {host!r} resolved to no addresses")
    return addresses


def assert_public_https_url(url: str, *, resolver: Resolver | None = None) -> None:
    """Raise UnsafeURLError unless ``url`` is https and every address its
    host resolves to (including anything an IPv6 form carries inside it)
    is globally routable.

    ``resolver`` overrides how names are turned into addresses; tests
    inject one so the suite does not depend on live DNS.
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURLError("URL must not be empty")

    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise UnsafeURLError(f"URL must use https, got {parts.scheme!r}")
    if "@" in parts.netloc:
        raise UnsafeURLError("URL must not embed credentials")

    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL must include a host")
    if host in _METADATA_HOSTS:
        raise UnsafeURLError(f"refusing to reach cloud metadata host {host!r}")

    for address in _addresses_for(host, resolver):
        _check_address(address, host=host)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_url_safety.py -v`
Expected: PASS (all cases in Step 1)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/url_safety.py backend/tests/test_url_safety.py
git commit -m "feat(security): add address-based SSRF validator for customer-supplied URLs"
```

---

### Task 2: Webhook endpoint create/update

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/webhook_dispatch_service.py:136-171` (`create_endpoint`, `update_endpoint`)
- Test: `backend/tests/e2e/test_webhook_endpoint_ssrf.py`

**Interfaces:**
- Consumes: `assert_public_https_url(url: str) -> None` and `UnsafeURLError` from Task 1's `app.core.url_safety`.
- Produces: `create_endpoint`/`update_endpoint` now raise `UnsafeURLError` for an unsafe `url`, surfaced by FastAPI as `400 {"detail": ..., "code": "UNSAFE_URL"}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/e2e/test_webhook_endpoint_ssrf.py
"""SSRF checks on webhook endpoint create/update.

An org ADMIN sets this URL and Parry's own backend POSTs to it on a
schedule — the same stored-SSRF shape as an MCP server URL, but for a
customer notification target rather than a tool source.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_rejects_a_private_target(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://169.254.169.254/hook", "event_types": []},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_create_rejects_http(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "http://example.com/hook", "event_types": []},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_create_accepts_a_public_target(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://example.com/hook", "event_types": []},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_update_rejects_repointing_at_a_private_target(
    admin_client: AsyncClient, seeded_db: dict
) -> None:
    create = await admin_client.post(
        "/api/v1/webhooks/endpoints",
        json={"url": "https://example.com/hook", "event_types": []},
    )
    endpoint_id = create.json()["id"]

    resp = await admin_client.patch(
        f"/api/v1/webhooks/endpoints/{endpoint_id}",
        json={"url": "https://10.0.0.5/hook"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/e2e/test_webhook_endpoint_ssrf.py -v`
Expected: FAIL — `test_create_rejects_a_private_target` and `test_create_rejects_http` get `201` instead of `400`; `test_update_rejects_repointing_at_a_private_target` gets `200` instead of `400`. (Requires local Postgres on `:5434`; skipped otherwise per `backend/tests/e2e/conftest.py`.)

- [ ] **Step 3: Wire the validator into create/update, register the exception handler**

In `backend/app/services/webhook_dispatch_service.py`, add the import and validate at the top of both functions:

```python
from app.core.url_safety import assert_public_https_url
```

```python
async def create_endpoint(
    db: AsyncSession,
    org_id: uuid.UUID,
    url: str,
    event_types: list[str],
    description: str | None = None,
) -> WebhookEndpoint:
    assert_public_https_url(url)
    endpoint = WebhookEndpoint(
        org_id=org_id,
        url=url,
        secret=generate_secret(),
        description=description,
        event_types=event_types,
    )
    db.add(endpoint)
    await db.flush()
    ...
```

```python
async def update_endpoint(
    db: AsyncSession,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    **updates: Any,
) -> WebhookEndpoint:
    from app.core.exceptions import NotFoundError

    endpoint = await get_endpoint(db, org_id, endpoint_id)
    if endpoint is None:
        raise NotFoundError("WebhookEndpoint", str(endpoint_id))

    if updates.get("url") is not None:
        assert_public_https_url(updates["url"])

    for key, value in updates.items():
        if value is not None:
            setattr(endpoint, key, value)
    ...
```

In `backend/app/main.py`, add the import next to the existing exception imports and register a handler next to `policy_violation_handler`:

```python
from app.core.url_safety import UnsafeURLError
```

```python
@app.exception_handler(UnsafeURLError)
async def unsafe_url_handler(request: Request, exc: UnsafeURLError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message, "code": exc.code},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/e2e/test_webhook_endpoint_ssrf.py tests/e2e/test_webhook_flow.py -v`
Expected: PASS — the new tests pass, and the pre-existing `test_webhook_flow.py` lifecycle test still passes (it only ever uses `https://example.com/webhook`, which stays valid).

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/services/webhook_dispatch_service.py backend/tests/e2e/test_webhook_endpoint_ssrf.py
git commit -m "fix(security): reject unsafe webhook endpoint URLs on create and update"
```

---

### Task 3: Webhook delivery revalidation

**Files:**
- Modify: `backend/app/workers/webhook_delivery_task.py:90-105` (`_deliver`)
- Test: `backend/tests/e2e/test_webhook_delivery_ssrf.py`

**Interfaces:**
- Consumes: `assert_public_https_url` from Task 1.
- Produces: no new public interface — `_deliver` now refuses to send if `endpoint.url` is unsafe *at send time*, independent of Task 2's write-time check, and records the refusal the same way it already records an `httpx` failure (`WebhookDelivery.error`, `endpoint.failure_count += 1`, task re-raises to trigger Celery's existing retry — this plan does not change retry behavior, which already retries ordinary delivery failures such as a `404`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/e2e/test_webhook_delivery_ssrf.py
"""Delivery-time SSRF revalidation.

This inserts a WebhookEndpoint directly (bypassing the service-layer
check from Task 2) to prove the send-time check in _deliver is a real,
independent second gate — not just a reflection of the write-time one.
A row can carry an unsafe URL today from data written before this
plan shipped, or from any future write path that forgets the check;
this test protects against both.
"""

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import WebhookDelivery, WebhookEndpoint
from tests.e2e.conftest import TEST_DB_URL


@pytest.mark.asyncio
async def test_delivery_refuses_a_private_target_and_records_it(
    db: AsyncSession, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.webhook_delivery_task import _deliver

    endpoint = WebhookEndpoint(
        org_id=seeded_db["org"].id,
        url="https://169.254.169.254/hook",
        secret="whsec_test",
        event_types=["detection.triggered"],
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)

    task_engine = create_async_engine(TEST_DB_URL, echo=False)
    task_factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.make_task_session_factory", lambda: task_factory)

    try:
        with pytest.raises(Exception, match="Webhook delivery failed"):
            await _deliver(str(endpoint.id), "test", json.dumps({"test": True}), 1)
    finally:
        await task_engine.dispose()

    deliveries = (
        await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
        )
    ).scalars().all()
    assert len(deliveries) == 1
    assert "link-local" in deliveries[0].error

    await db.refresh(endpoint)
    assert endpoint.failure_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/e2e/test_webhook_delivery_ssrf.py -v`
Expected: FAIL — `_deliver` currently reaches `httpx.AsyncClient(...).post(...)` and the assertion on `deliveries[0].error` finds an `httpx` connection error instead of `"link-local"`.

- [ ] **Step 3: Revalidate immediately before the HTTP call**

In `backend/app/workers/webhook_delivery_task.py`, inside `_deliver`, add the import next to the other local imports at the top of the function body and the check as the first line inside the existing `try` block around the send:

```python
async def _deliver(
    endpoint_id: str,
    event_type: str,
    payload_json: str,
    attempt: int,
) -> dict[str, Any]:
    import uuid

    import httpx

    from app.core.url_safety import assert_public_https_url
    from app.db.models import WebhookDelivery, WebhookEndpoint
    from app.db.session import make_task_session_factory
    from app.services.webhook_dispatch_service import compute_signature
    ...
```

```python
            try:
                assert_public_https_url(endpoint.url)
                async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
                    resp = await client.post(
                        endpoint.url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Parry-Signature": signature,
                            "X-Parry-Event": event_type,
                            "User-Agent": "Parry-Webhook/1.0",
                        },
                    )
                    status_code = resp.status_code
                    response_body = resp.text[:500] if resp.text else None

                    if resp.is_success:
                        endpoint.failure_count = 0
                    else:
                        endpoint.failure_count += 1
                        error = f"HTTP {status_code}"

            except Exception as e:
                endpoint.failure_count += 1
                error = str(e)[:500]
```

(Only the added `assert_public_https_url(endpoint.url)` line changes; the surrounding `try`/`except Exception as e` already catches it and folds it into `error` the same way it folds an `httpx` failure — no new except clause needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/e2e/test_webhook_delivery_ssrf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/webhook_delivery_task.py backend/tests/e2e/test_webhook_delivery_ssrf.py
git commit -m "fix(security): revalidate webhook target URL immediately before delivery"
```

---

### Task 4: Alert config write-time validation

**Files:**
- Modify: `backend/app/api/v1/alerts.py:128-174` (`update_alert_config`)
- Test: `backend/tests/e2e/test_alert_config_ssrf.py`

**Interfaces:**
- Consumes: `assert_public_https_url` from Task 1.
- Produces: `PUT /api/v1/alerts` now raises `UnsafeURLError` (→ `400`, same handler as Task 2) for an unsafe `slack_webhook_url` or `webhook_url`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/e2e/test_alert_config_ssrf.py
"""SSRF checks on alert config's customer-supplied webhook targets.

Pydantic's HttpUrl on AlertConfigUpdate already rejects a malformed
URL; it does not and cannot reject a well-formed one that points at
169.254.169.254 or an internal host. That is this test's job.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rejects_a_private_webhook_url(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"webhook_url": "https://169.254.169.254/hook"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_rejects_a_private_slack_webhook_url(
    admin_client: AsyncClient, seeded_db: dict
) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"slack_webhook_url": "https://10.0.0.5/hook"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_accepts_a_public_webhook_url(admin_client: AsyncClient, seeded_db: dict) -> None:
    resp = await admin_client.put(
        "/api/v1/alerts", json={"webhook_url": "https://example.com/hook"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["webhook_url"] == "https://example.com/hook"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/e2e/test_alert_config_ssrf.py -v`
Expected: FAIL — the two rejection tests get `200` instead of `400`.

- [ ] **Step 3: Validate at write time**

In `backend/app/api/v1/alerts.py`, add the import and two checks in `update_alert_config`:

```python
from app.core.url_safety import assert_public_https_url
```

```python
    if body.slack_webhook_url is not None:
        config["slack_webhook_url"] = str(body.slack_webhook_url)
        assert_public_https_url(config["slack_webhook_url"])

    if body.alert_emails is not None:
        config["alert_emails"] = [str(e) for e in body.alert_emails]

    if body.webhook_url is not None:
        config["webhook_url"] = str(body.webhook_url)
        assert_public_https_url(config["webhook_url"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/e2e/test_alert_config_ssrf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/alerts.py backend/tests/e2e/test_alert_config_ssrf.py
git commit -m "fix(security): reject unsafe Slack/webhook alert targets on config update"
```

---

### Task 5: Alert dispatch revalidation

**Files:**
- Modify: `backend/app/services/alert_service.py:141-165` (`send_slack_alert`), `:408-431` (`send_webhook_alert`)
- Test: `backend/tests/test_alert_service_ssrf.py`

**Interfaces:**
- Consumes: `assert_public_https_url`, `UnsafeURLError` from Task 1.
- Produces: no signature change — `send_slack_alert`/`send_webhook_alert` still return `bool`; an unsafe URL now yields `False` (logged, `record_alert_sent(..., success=False)`) instead of an unhandled exception.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_alert_service_ssrf.py
"""Send-time SSRF revalidation for alert dispatch.

Same TOCTOU shape as webhook delivery (Task 3): the URL was checked
when it was written to org.alert_config, but only revalidating here,
immediately before the network call, closes the window where the
config's DNS could be repointed in between.
"""

import pytest

from app.db.models import Incident
from app.services.alert_service import send_slack_alert, send_webhook_alert


@pytest.mark.asyncio
async def test_send_webhook_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    result = await send_webhook_alert("https://169.254.169.254/hook", sample_incident)
    assert result is False


@pytest.mark.asyncio
async def test_send_slack_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    result = await send_slack_alert("https://10.0.0.5/hook", sample_incident)
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_alert_service_ssrf.py -v`
Expected: FAIL — both calls currently attempt a real `httpx` connection to a private address (times out or connection-refused, not the fast, deterministic `UnsafeURLError` path this task adds); depending on the sandbox's network policy this may hang or error rather than cleanly returning `False`.

- [ ] **Step 3: Revalidate immediately before each send**

In `backend/app/services/alert_service.py`, add the import once near the top of the file:

```python
from app.core.url_safety import UnsafeURLError, assert_public_https_url
```

Update `send_slack_alert`:

```python
async def send_slack_alert(
    webhook_url: str, incident: Incident, dashboard_url: str | None = None
) -> bool:
    """POST the incident to a Slack incoming webhook. Returns True on success."""
    payload = build_slack_payload(incident, dashboard_url)
    try:
        assert_public_https_url(webhook_url)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        log.info(
            "alert.slack_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
        )
        record_alert_sent(channel="slack", success=True)
        return True
    except (httpx.HTTPError, UnsafeURLError) as e:
        log.warning(
            "alert.slack_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="slack", success=False)
        return False
```

Update `send_webhook_alert` the same way:

```python
async def send_webhook_alert(
    webhook_url: str,
    incident: Incident,
    dashboard_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    """POST a generic JSON payload to an arbitrary webhook URL."""
    payload = build_webhook_payload(incident, dashboard_url)
    try:
        assert_public_https_url(webhook_url)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers or {})
            resp.raise_for_status()
        log.info(
            "alert.webhook_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
            status=resp.status_code,
        )
        record_alert_sent(channel="webhook", success=True)
        return True
    except (httpx.HTTPError, UnsafeURLError) as e:
        log.warning(
            "alert.webhook_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="webhook", success=False)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_alert_service_ssrf.py -v`
Expected: PASS — both return `False` immediately, no network call attempted.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS — no regressions in `test_webhook_flow.py`, `test_webhook_service.py`, or any alert-service test that already exercises `send_slack_alert`/`send_webhook_alert` with a public URL.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/alert_service.py backend/tests/test_alert_service_ssrf.py
git commit -m "fix(security): revalidate alert webhook targets immediately before send"
```

---

## Self-Review

**1. Spec coverage:** Problem Statement names two gaps (webhook endpoints, alert config) and two layers each (write-time, send-time) = 4 concrete requirements. Task 2 (webhook write-time), Task 3 (webhook send-time), Task 4 (alert write-time), Task 5 (alert send-time) — all four covered. Task 1 underlies all of them. The explicitly-out-of-scope items (Okta client, PagerDuty/Opsgenie fixed URLs) have no task, by design, and the Problem Statement says why.

**2. Placeholder scan:** No TBD/TODO, no "add appropriate error handling," no test omitted — every test has real assertions and every implementation step has complete code.

**3. Type consistency:** `assert_public_https_url(url: str, *, resolver: Resolver | None = None) -> None` and `UnsafeURLError` are defined once in Task 1 and referenced identically (same names, same import path `app.core.url_safety`) in Tasks 2–5. `send_slack_alert`/`send_webhook_alert` keep their existing `-> bool` signature across the whole plan.

**4. Review Focus coverage:**
- Update-not-just-create → Task 2's `test_update_rejects_repointing_at_a_private_target`.
- Send-time revalidation → Task 3's `test_delivery_refuses_a_private_target_and_records_it` and Task 5's two tests.
- Embedded-v4 IPv6 → Task 1's `test_rejects_nat64_embedded_metadata_ip`.
- Stable `code` field → asserted directly (`resp.json()["code"] == "UNSAFE_URL"`) in Tasks 2 and 4's e2e tests.
- Failure must not silently pass → Task 5's tests assert `False` is returned, not an exception; Task 3's test asserts the failure is written to `WebhookDelivery.error` and `failure_count`, not swallowed.
