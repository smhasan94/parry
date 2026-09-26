# MCP DNS-Rebinding Pinning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the DNS-rebinding gap in `SentinelMCPClient.http()`/`.sse()` by connecting to the exact address `validate_server_url` already checked, instead of letting the transport re-resolve the hostname and race a changed DNS record.

**Architecture:** `validate.py` gains a `validate_and_pin()` entry point that returns the canonical URL *and* the first validated address. `client.py` threads that address through a custom `httpcore` network backend that ignores the hostname handed to it at connect time and dials the pinned IP instead, while TLS server-name verification still checks the real hostname (untouched, since httpcore derives SNI from the request origin, not from the backend).

**Tech Stack:** Python 3.12, httpx 0.28.1, httpcore 1.0.9 (both already pinned in `sdk/pyproject.toml`), pytest + pytest-asyncio.

**Spec:** No separate spec doc — the requirement is the single paragraph in `docs/mcp-security.md`'s "What's not yet supported" section (quoted in full below) plus the identical explanation already in `sdk/parry/mcp/validate.py`'s module docstring. Both are the spec for this plan; Task 3 updates them once the gap is closed.

> **DNS rebinding.** Validation resolves the hostname, but the transport resolves it again when it dials, so a record that changes between those two moments is not caught. Closing this needs connect-time pinning — validating and connecting to the same address. A *static* hostile record is caught, and redirects are refused, so what remains is the timing attack rather than the easy version. Use `allow_private=False` (the default) and egress policy for the rest.

## Investigation notes (why this is the only real gap here)

The memory note that seeded this plan claimed "MCP HTTP + SSE transports — stdio only." That is **no longer true** and was already stale by the time this plan was written: `SentinelMCPClient.http()` and `.sse()` are fully implemented (`sdk/parry/mcp/client.py:196-283`), documented (`docs/mcp-security.md:129-189`), SSRF-validated (`sdk/parry/mcp/validate.py`), TLS-verified with no opt-out, and redirect-refusing (`_no_redirect_client`, `client.py:64-81`). No task in this plan re-does that work.

Two things this plan does **not** attempt, and why:

- **The manifest-buffering gap** (`_check_manifest_bounds` bounds a manifest after it's parsed, not the bytes a server can make the transport buffer first) is genuinely blocked: the fix needs a per-message cap inside the transport, before the JSON-RPC parse, and the `mcp` SDK does not expose that hook. `client.py:41-57` already documents this precisely; there is nothing actionable to plan until upstream `mcp` adds the hook. Left as a tracked, deferred item — not a task here.
- **Jailbreak detector recall, backend SSRF audit, async PDF reports, doc-drift cleanup** are separate open items covered by sibling plans, not this one.

The one item in `docs/mcp-security.md`'s "not yet supported" list with a stated, buildable fix direction — "closing this needs connect-time pinning" — is DNS rebinding, and it's what this plan builds.

## Global Constraints

- TLS verification stays unconditionally on (`verify=True`) — this plan must not introduce a path that skips certificate validation. (Existing rule, `docs/mcp-security.md:157`.)
- Redirects stay refused (`follow_redirects=False`) — pinning happens *in addition to* that, not instead of it.
- `httpx>=0.28.0` / `mcp>=1.0.0` floors in `sdk/pyproject.toml` are unchanged; this plan adds no new dependency (httpcore is already an httpx transitive dependency at 1.0.9, confirmed installed).
- No behavior change for `stdio` transport — pinning only applies where a hostname is resolved over the network (`http`/`sse`).
- `validate_server_url()`'s existing public signature and return type (`str`) must not change — it has existing callers and tests (`sdk/tests/test_mcp_validate.py`) that assert a bare string back. Add a new function alongside it.

## Review Focus

- **IPv6 pinned address correctness.** `_addresses_for()` can return a bare IPv6 literal (e.g. `::1`, or an unwrapped 6to4/NAT64/Teredo address). The pinned backend must hand that literal to `anyio.connect_tcp` unbracketed and unmodified — a test exercises an IPv6 pin, not just IPv4.
- **Multiple resolved addresses, first one unreachable.** All addresses a hostname resolves to are validated, but only the first is pinned. If that address is temporarily unreachable while a second (also-validated) address would succeed, this plan's behavior is to fail rather than silently fail over to a live re-resolve — that's the intended trade (a fallback re-resolve is exactly the TOCTOU window being closed). Document this in the docstring so it isn't mistaken for a bug later.
- **`sandbox=True` / `_fake_manifest` test path must stay untouched.** Both skip `_OPENERS[...]` entirely (`client.py:305-312`), so they never build an httpx transport at all. Confirm no task accidentally requires a pinned address on that path (it should tolerate `pinned_address=None`).
- **Private-httpx-internals fragility.** `create_ssl_context` and `httpcore._backends.anyio.AnyIOBackend` are private/internal import paths, not part of httpx's public API. An httpx/httpcore upgrade could rename or remove them silently. Task 2 adds a standalone guard test that imports them and fails loudly (not via some unrelated downstream error) if they're gone, so a version bump surfaces this immediately in CI rather than as a runtime `ImportError` in production.
- **Backend fail-open on registration must not fire on a pinning failure.** `_register_with_parry()` fails open when the Parry backend is unreachable (`client.py:427-435`) — that's a *different* failure than "MCP server itself is unreachable at its pinned address," which should raise `ConnectError`/`MCPManifestError` as it does today, not be swallowed. No task changes `_register_with_parry`; this is a note to the reviewer to confirm pinning failures surface as connection errors from `_open_http_session`/`_open_sse_session`, same as any other dial failure would.

---

## File Structure

- **Modify `sdk/parry/mcp/validate.py`:** add `ValidatedURL` (frozen dataclass) and `validate_and_pin()`; refactor the existing body of `validate_server_url()` into a shared private `_validate()` so both public functions share one implementation.
- **Modify `sdk/parry/mcp/client.py`:** add `_PinnedNetworkBackend` (httpcore network backend that ignores the requested host) and `_PinnedHTTPTransport` (httpx transport wired to that backend); extend `_no_redirect_client()` with an optional `pinned_address` keyword; store the pinned address in `transport_kwargs` from `_remote()`; read it back in `_open_http_session`/`_open_sse_session`.
- **Modify `sdk/tests/test_mcp_validate.py`:** tests for `validate_and_pin()`.
- **Modify `sdk/tests/test_mcp_client.py`:** tests for the pinned backend/transport and the guard test for the private httpx/httpcore imports.
- **Modify `docs/mcp-security.md`:** replace the DNS-rebinding "not yet supported" bullet with a description of the closed behavior, and correct the stale "stdio only" framing this plan's investigation notes found.

---

### Task 1: Expose the pinned address from `validate_server_url`

**Files:**
- Modify: `sdk/parry/mcp/validate.py:196-267` (the current `validate_server_url` body)
- Test: `sdk/tests/test_mcp_validate.py`

**Interfaces:**
- Produces: `ValidatedURL` (frozen dataclass, fields `canonical_url: str`, `pinned_address: str`) and `validate_and_pin(url: str, *, allow_insecure: bool = False, allow_private: bool = False, resolver: Resolver | None = None) -> ValidatedURL`, both importable from `parry.mcp.validate`.
- Consumes: nothing new — reuses `_addresses_for`, `_check_address`, `_is_loopback_host` already in this module.
- `validate_server_url(...) -> str` keeps its exact existing signature and behavior (delegates to the same shared code, returns only `canonical_url`).

- [ ] **Step 1: Write the failing tests**

Add to `sdk/tests/test_mcp_validate.py`:

```python
from parry.mcp.validate import ValidatedURL, validate_and_pin


class TestValidateAndPin:
    """validate_and_pin returns the same canonical URL as validate_server_url,
    plus the address that was actually checked — the one connect-time pinning
    (client.py) will dial instead of letting the transport re-resolve.
    """

    def test_returns_canonical_url_and_pinned_address(self) -> None:
        result = validate_and_pin(
            "https://mcp.example.com/mcp/", resolver=resolves_to(PUBLIC_IP)
        )
        assert result == ValidatedURL(
            canonical_url="https://mcp.example.com/mcp",
            pinned_address=PUBLIC_IP,
        )

    def test_pins_first_resolved_address_when_host_has_several(self) -> None:
        second_public = "93.184.216.35"
        result = validate_and_pin(
            "https://mcp.example.com/mcp",
            resolver=resolves_to(PUBLIC_IP, second_public),
        )
        assert result.pinned_address == PUBLIC_IP

    def test_pins_ipv6_literal_unbracketed(self) -> None:
        # A bare IPv6 literal in the URL is already an address — no
        # resolver call — and must come back without brackets, since
        # that's what anyio.connect_tcp expects as remote_host.
        result = validate_and_pin("https://[2001:db8::1]/mcp")
        assert result.pinned_address == "2001:db8::1"

    def test_still_refuses_unsafe_addresses(self) -> None:
        with pytest.raises(MCPURLError):
            validate_and_pin(
                "https://mcp.example.com/mcp",
                resolver=resolves_to("169.254.169.254"),
            )

    def test_validate_server_url_unchanged(self) -> None:
        # Existing public function keeps its exact contract: a bare str.
        assert (
            validate_server_url("https://mcp.example.com/mcp", resolver=public)
            == "https://mcp.example.com/mcp"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sdk && uv run pytest tests/test_mcp_validate.py::TestValidateAndPin -v`
Expected: FAIL with `ImportError: cannot import name 'ValidatedURL'` (or `'validate_and_pin'`) from `parry.mcp.validate`.

- [ ] **Step 3: Refactor `validate.py` to share one implementation**

In `sdk/parry/mcp/validate.py`, add the import and dataclass near the top (after the existing imports):

```python
from dataclasses import dataclass
```

Replace the existing `validate_server_url` function (currently `client.py:196-267`... — in this file, the function starting `def validate_server_url(`) with:

```python
@dataclass(frozen=True)
class ValidatedURL:
    """Result of validating a remote MCP server URL.

    ``pinned_address`` is the address ``canonical_url``'s host resolved
    to and had checked against every rule in this module. Connecting to
    it directly — instead of letting the transport resolve the hostname
    again — is what closes the DNS-rebinding gap: there is no second
    lookup left to race. When the URL already named a literal address
    (IPv4 or IPv6, unbracketed), ``pinned_address`` is just that address.
    """

    canonical_url: str
    pinned_address: str


def validate_server_url(
    url: str,
    *,
    allow_insecure: bool = False,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> str:
    """Return the canonical URL, or raise ``MCPURLError``.

    Canonical form drops the query and fragment: an MCP endpoint is
    addressed by scheme, host and path, and those two fields are where
    a token would sit. Dropping them here means the value handed to the
    backend cannot carry a credential even by accident.

    ``resolver`` overrides how names are turned into addresses. Tests
    inject one so the suite does not depend on live DNS.
    """
    return _validate(
        url,
        allow_insecure=allow_insecure,
        allow_private=allow_private,
        resolver=resolver,
    ).canonical_url


def validate_and_pin(
    url: str,
    *,
    allow_insecure: bool = False,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> ValidatedURL:
    """Like ``validate_server_url``, but also return the address to pin.

    Used by ``SentinelMCPClient.http``/``.sse`` so the transport can
    connect to the exact address that was checked, rather than letting
    it re-resolve the hostname at dial time.
    """
    return _validate(
        url,
        allow_insecure=allow_insecure,
        allow_private=allow_private,
        resolver=resolver,
    )


def _validate(
    url: str,
    *,
    allow_insecure: bool,
    allow_private: bool,
    resolver: Resolver | None,
) -> ValidatedURL:
    raw = (url or "").strip()
    if not raw:
        raise MCPURLError("MCP server URL must not be empty")
    if len(raw) > MAX_URL_CHARS:
        raise MCPURLError(f"MCP server URL exceeds {MAX_URL_CHARS} characters")

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise MCPURLError(
            f"unsupported MCP server URL scheme {parts.scheme!r}; expected http or https"
        )

    if "@" in parts.netloc:
        raise MCPURLError(
            "MCP server URL must not embed credentials; pass them via headers= instead"
        )

    try:
        port = parts.port
    except ValueError as exc:
        raise MCPURLError("MCP server URL has an invalid port") from exc

    host = (parts.hostname or "").lower()
    if not host:
        raise MCPURLError("MCP server URL must include a host")

    if host in _METADATA_HOSTS:
        raise MCPURLError(f"refusing to connect to cloud metadata host {host!r}")

    is_loopback = _is_loopback_host(host)

    addresses = _addresses_for(host, resolver)
    for address in addresses:
        _check_address(
            address,
            host=host,
            allow_private=allow_private,
            allow_loopback=is_loopback,
        )

    if scheme == "http" and not is_loopback and not allow_insecure:
        raise MCPURLError(
            f"refusing to fetch an MCP manifest over plaintext http from {host}; "
            "use https, or pass allow_insecure=True if you accept the risk"
        )

    # urlsplit strips the brackets off a v6 literal; without them back
    # the port delimiter is ambiguous and the URL will not parse again.
    netloc = f"[{host}]" if ":" in host else host
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"

    canonical_url = urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))
    return ValidatedURL(canonical_url=canonical_url, pinned_address=addresses[0])
```

Note the pinned address is `addresses[0]` — the first entry `_addresses_for` returned, which by construction already passed every check in the loop above (an unsafe entry anywhere in the list raises before this line is reached).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sdk && uv run pytest tests/test_mcp_validate.py -v`
Expected: PASS, all tests including the pre-existing ones in this file (the refactor must not change any existing test's outcome).

- [ ] **Step 5: Commit**

```bash
git add sdk/parry/mcp/validate.py sdk/tests/test_mcp_validate.py
git commit -m "feat(mcp): expose the validated address for connect-time pinning"
```

---

### Task 2: Pin the transport's TCP connection to the validated address

**Files:**
- Modify: `sdk/parry/mcp/client.py:23-116` (imports and the `_no_redirect_client`/bounds section), `:252-283` (`_remote`), `:348-388` (`_open_http_session`/`_open_sse_session`)
- Test: `sdk/tests/test_mcp_client.py`

**Interfaces:**
- Consumes: `parry.mcp.validate.validate_and_pin` and `ValidatedURL` from Task 1.
- Produces: `_PinnedNetworkBackend` (class), `_PinnedHTTPTransport` (class), and `_no_redirect_client(headers=None, timeout=None, auth=None, pinned_address: str | None = None) -> httpx.AsyncClient` (extended signature — backward compatible, `pinned_address` defaults to `None` and reproduces today's behavior exactly).

- [ ] **Step 1: Write the failing tests**

Add to `sdk/tests/test_mcp_client.py`:

```python
import httpcore
import httpx._transports.default as _httpx_default_transport

from parry.mcp.client import _no_redirect_client, _PinnedHTTPTransport, _PinnedNetworkBackend


def test_private_httpx_internals_this_module_relies_on_still_exist() -> None:
    """Guard test: _PinnedHTTPTransport reaches into httpx/httpcore
    internals (create_ssl_context, AnyIOBackend) that aren't part of
    httpx's public API. If an httpx/httpcore upgrade removes or renames
    either, this fails here — loudly, at the source — instead of as a
    confusing runtime error inside a real MCP connection attempt.
    """
    assert hasattr(_httpx_default_transport, "create_ssl_context")
    from httpcore._backends.anyio import AnyIOBackend

    assert issubclass(_PinnedNetworkBackend, AnyIOBackend)


class TestPinnedNetworkBackend:
    async def test_connects_to_pinned_address_not_requested_host(self, monkeypatch) -> None:
        seen: dict = {}

        async def fake_connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            seen["host"] = host
            seen["port"] = port
            return object()

        monkeypatch.setattr(
            "httpcore._backends.anyio.AnyIOBackend.connect_tcp", fake_connect_tcp
        )
        backend = _PinnedNetworkBackend("93.184.216.34")
        await backend.connect_tcp("mcp.example.com", 443)
        assert seen == {"host": "93.184.216.34", "port": 443}

    async def test_connects_to_pinned_ipv6_address_unbracketed(self, monkeypatch) -> None:
        seen: dict = {}

        async def fake_connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            seen["host"] = host
            return object()

        monkeypatch.setattr(
            "httpcore._backends.anyio.AnyIOBackend.connect_tcp", fake_connect_tcp
        )
        backend = _PinnedNetworkBackend("2001:db8::1")
        await backend.connect_tcp("mcp.example.com", 443)
        assert seen["host"] == "2001:db8::1"


class TestNoRedirectClientPinning:
    def test_pinned_address_none_matches_current_behavior(self) -> None:
        client = _no_redirect_client()
        transport = client._transport
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert not isinstance(transport, _PinnedHTTPTransport)

    def test_pinned_address_set_builds_pinned_transport(self) -> None:
        client = _no_redirect_client(pinned_address="93.184.216.34")
        transport = client._transport
        assert isinstance(transport, _PinnedHTTPTransport)
        backend = transport._pool._network_backend
        assert isinstance(backend, _PinnedNetworkBackend)
        assert backend._pinned_address == "93.184.216.34"

    def test_pinned_transport_still_verifies_tls(self) -> None:
        client = _no_redirect_client(pinned_address="93.184.216.34")
        ssl_context = client._transport._pool._ssl_context
        assert ssl_context.verify_mode.name == "CERT_REQUIRED"

    def test_pinned_transport_still_refuses_redirects(self) -> None:
        client = _no_redirect_client(pinned_address="93.184.216.34")
        assert client.follow_redirects is False


async def test_remote_client_stores_pinned_address(patch_httpx) -> None:
    """SentinelMCPClient.http()/.sse() thread the validated address
    through to transport_kwargs, where _open_http_session/_open_sse_session
    read it back to build the pinned transport.
    """
    patch_httpx(_ok_handler({}))
    client = SentinelMCPClient.http(
        url="https://mcp.example.com/mcp",
        agent_id="dev-assistant",
        api_key="sk-parry-test",
        resolver=resolves_public,
    )
    assert client._transport_kwargs["pinned_address"] == PUBLIC_IP
```

`_ok_handler` doesn't exist yet in this file if the earlier read didn't show it — check for it before adding; if it's not already defined, add this small helper next to `_parry_handler`:

```python
def _ok_handler(captured: dict):
    return _parry_handler(
        status=200,
        body={
            "server_id": "srv-1",
            "trust_level": "observed",
            "manifest_changed": False,
            "new_hash": "abc",
            "detections": [],
        },
        captured=captured,
    )
```

(Skip adding it if grep shows it already exists in the file — the earlier reads of this file showed it referenced at lines 253/280/291 without showing its definition, so confirm before duplicating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sdk && uv run pytest tests/test_mcp_client.py -k "Pinned or pinned" -v`
Expected: FAIL with `ImportError: cannot import name '_PinnedHTTPTransport'` (or `_PinnedNetworkBackend`) from `parry.mcp.client`.

- [ ] **Step 3: Implement the pinned backend and transport in `client.py`**

Add imports near the top of `sdk/parry/mcp/client.py` (alongside the existing `import anyio` / `import httpx`):

```python
import functools

import httpcore
from httpcore._backends.anyio import AnyIOBackend
from httpx._transports.default import create_ssl_context
```

Add these two classes directly below `_no_redirect_client` (after its closing line, before `_check_manifest_bounds`):

```python
class _PinnedNetworkBackend(AnyIOBackend):
    """TCP backend that dials a fixed address regardless of the requested host.

    ``validate_and_pin`` already resolved the MCP server's hostname and
    checked every address it returned against the SSRF rules. Connecting
    here to that same address — instead of letting anyio resolve the
    hostname again — is what closes the DNS-rebinding gap documented in
    ``docs/mcp-security.md``: a record that changes between validation
    and connection no longer matters, because there is no second lookup
    left to race.

    TLS server-name verification is unaffected: httpcore derives SNI
    from the request's origin host, not from what this backend dials,
    so the certificate is still checked against the real hostname.
    """

    def __init__(self, pinned_address: str) -> None:
        super().__init__()
        self._pinned_address = pinned_address

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        return await super().connect_tcp(
            self._pinned_address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _PinnedHTTPTransport(httpx.AsyncHTTPTransport):
    """AsyncHTTPTransport that always connects to ``pinned_address``.

    Deliberately does not call ``httpx.AsyncHTTPTransport.__init__`` —
    that always builds a pool with the default hostname-resolving
    backend. This builds the same shape of pool with
    ``_PinnedNetworkBackend`` instead; ``handle_async_request`` and
    ``aclose`` are inherited unchanged since they only touch ``self._pool``.

    ``create_ssl_context`` and ``AnyIOBackend`` are httpx/httpcore
    internals, not public API — see the guard test
    ``test_private_httpx_internals_this_module_relies_on_still_exist``.
    """

    def __init__(self, pinned_address: str) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=create_ssl_context(verify=True),
            network_backend=_PinnedNetworkBackend(pinned_address),
            retries=0,
        )
```

Now extend `_no_redirect_client` (replace the existing function body):

```python
def _no_redirect_client(
    headers: dict[str, str] | None = None,
    timeout: Any = None,
    auth: Any = None,
    pinned_address: str | None = None,
) -> httpx.AsyncClient:
    """httpx client for the MCP transports, with redirects disabled.

    Validating the URL only proves the *first* hop is acceptable. A
    permitted host answering 302 → http://169.254.169.254/ would walk
    straight past every check, so the transport never follows.

    ``pinned_address``, when given, forces the TCP connection to that
    exact address instead of letting the transport re-resolve the
    hostname — see ``_PinnedNetworkBackend``.
    """
    transport = _PinnedHTTPTransport(pinned_address) if pinned_address else None
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        verify=True,
        transport=transport,
    )
```

- [ ] **Step 4: Thread the pinned address from `_remote()` through to both session openers**

In `_remote()` (the classmethod currently at `client.py:252-283`), replace the `validate_server_url` call and the `transport_kwargs` dict:

```python
    @classmethod
    def _remote(
        cls,
        transport: str,
        *,
        url: str,
        headers: dict[str, str] | None,
        auth: Any,
        allow_insecure: bool,
        allow_private: bool,
        resolver: Resolver | None,
        **parry_kwargs: Any,
    ) -> SentinelMCPClient:
        # Validate before construction so a refused URL fails at the
        # call site the developer wrote, not later inside a context
        # manager where the traceback points at our internals.
        validated = validate_and_pin(
            url,
            allow_insecure=allow_insecure,
            allow_private=allow_private,
            resolver=resolver,
        )
        return cls(
            transport=transport,
            transport_kwargs={
                "url": validated.canonical_url,
                "headers": headers or {},
                "auth": auth,
                "server_uri": validated.canonical_url,
                "pinned_address": validated.pinned_address,
            },
            **parry_kwargs,
        )
```

Update the import line near the top of the file from:

```python
from parry.mcp.validate import Resolver, validate_server_url
```

to:

```python
from parry.mcp.validate import Resolver, validate_and_pin
```

In `_open_http_session` (`client.py:348-371`), change the `httpx_client_factory` argument:

```python
        assert self._stack is not None
        read, write, _get_session_id = await self._stack.enter_async_context(
            streamable_http_client(
                self._transport_kwargs["url"],
                headers=self._transport_kwargs.get("headers") or None,
                auth=self._transport_kwargs.get("auth"),
                timeout=self.timeout,
                httpx_client_factory=functools.partial(
                    _no_redirect_client,
                    pinned_address=self._transport_kwargs.get("pinned_address"),
                ),
            )
        )
```

In `_open_sse_session` (`client.py:373-388`), the same change:

```python
        assert self._stack is not None
        read, write = await self._stack.enter_async_context(
            sse_client(
                self._transport_kwargs["url"],
                headers=self._transport_kwargs.get("headers") or None,
                auth=self._transport_kwargs.get("auth"),
                timeout=self.timeout,
                httpx_client_factory=functools.partial(
                    _no_redirect_client,
                    pinned_address=self._transport_kwargs.get("pinned_address"),
                ),
            )
        )
```

`stdio`'s `transport_kwargs` never gets a `"pinned_address"` key, so `.get("pinned_address")` is `None` there too — moot, since `_open_stdio_session` never calls `_no_redirect_client` at all.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd sdk && uv run pytest tests/test_mcp_client.py tests/test_mcp_validate.py -v`
Expected: PASS — every test in both files, including all pre-existing ones (in particular `test_clean_manifest_connects_ok`, `test_unsafe_urls_fail_at_construction`, and `test_private_url_connects_when_opted_in`, which exercise the `sandbox`/`_fake_manifest` path and must be completely unaffected by this change).

- [ ] **Step 6: Run the full SDK suite**

Run: `cd sdk && uv run pytest -v`
Expected: PASS, no regressions elsewhere (this plan's `Global Constraints` claims a 160-test-green baseline per project memory — confirm the count didn't drop, only grew).

- [ ] **Step 7: Commit**

```bash
git add sdk/parry/mcp/client.py sdk/tests/test_mcp_client.py
git commit -m "feat(mcp): pin remote transport connections to the validated address"
```

---

### Task 3: Correct the docs

**Files:**
- Modify: `docs/mcp-security.md:225-243` (the "What's not yet supported" section)

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Replace the DNS-rebinding bullet**

In `docs/mcp-security.md`, remove this bullet from "What's not yet supported":

```markdown
- **DNS rebinding.** Validation resolves the hostname, but the
  transport resolves it again when it dials, so a record that changes
  between those two moments is not caught. Closing this needs
  connect-time pinning — validating and connecting to the same address.
  A *static* hostile record is caught, and redirects are refused, so
  what remains is the timing attack rather than the easy version. Use
  `allow_private=False` (the default) and egress policy for the rest.
```

and add this paragraph to the "Remote servers (HTTP and SSE)" section instead, directly after the existing rules table (after the line ending "...the timeout is what bounds that today."):

```markdown
The address that passes these checks is the one the transport connects
to — `http`/`sse` clients pin the TCP connection to the first validated
address rather than letting the transport resolve the hostname a
second time at dial. A record that changes between validation and
connection no longer matters, because there is no second lookup left
to race. TLS server-name verification still checks the real hostname,
unaffected by which address the connection was pinned to.
```

- [ ] **Step 2: Fix the manifest-buffering paragraph's cross-reference (drive-by correction while in this file)**

No change needed here — re-read the paragraph at `docs/mcp-security.md:172-178` and confirm it still accurately describes `_check_manifest_bounds` after Task 1/2 (it does; those tasks don't touch manifest bounds). This step exists to make the reviewer actually re-check it rather than assume, since it sits two paragraphs above the text this task edits.

- [ ] **Step 3: Commit**

```bash
git add docs/mcp-security.md
git commit -m "docs(mcp): drop DNS rebinding from unsupported now that pinning closes it"
```

---

## Self-Review

**1. Spec coverage:** The spec (the single "not yet supported" paragraph) is fully addressed — Task 1 produces the pinned address, Task 2 makes the transport dial it, Task 3 updates the doc to say so. No other claim in that section (manifest sharing, indirect injection) is touched, correctly — they're out of scope.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every step has literal code, exact file locations, and runnable commands.

**3. Type consistency:** `ValidatedURL.pinned_address: str` (Task 1) flows into `transport_kwargs["pinned_address"]: str` (Task 2 `_remote`) into `_no_redirect_client(pinned_address: str | None = None)` into `_PinnedHTTPTransport.__init__(pinned_address: str)` — consistent name and type throughout; `None` is only ever the "not pinning" sentinel, never passed to `_PinnedHTTPTransport`.

**4. Review Focus:** All five items have an owning test — IPv6 pinning (Task 2, `test_connects_to_pinned_ipv6_address_unbracketed` and Task 1's `test_pins_ipv6_literal_unbracketed`), first-address-only pinning documented in the `ValidatedURL` docstring and asserted by `test_pins_first_resolved_address_when_host_has_several`, sandbox/`_fake_manifest` path covered by re-running the full existing suite in Task 2 Step 5, private-internals fragility covered by the dedicated guard test in Task 2 Step 1, and the fail-open/pinning-failure distinction is a reviewer note (no code changes `_register_with_parry`, so no new test is owed — confirmed by inspection, not asserted away).
