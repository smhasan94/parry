"""SentinelMCPClient wrapper tests.

We don't exercise the real MCP stdio transport here — that needs a
subprocess binary and belongs in integration. Instead we use
``sandbox=True`` to skip the underlying MCP session entirely and
inject a fake manifest through the transport kwargs. The httpx round
trip to the Parry backend is stubbed via a MockTransport.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack, asynccontextmanager

import httpcore
import httpx
import httpx._transports.default as _httpx_default_transport
import pytest

from parry.mcp import MCPBlockedError, SentinelMCPClient
from parry.mcp.client import (
    MAX_MANIFEST_CHARS,
    MAX_MANIFEST_TOOLS,
    _no_redirect_client,
    _PinnedHTTPTransport,
    _PinnedNetworkBackend,
)
from parry.mcp.errors import MCPManifestError, MCPURLError
from parry.mcp.normalize import manifest_hash

# Remote URLs are judged by what they resolve to, so every test that
# constructs one injects its own answer rather than depending on DNS.
PUBLIC_IP = "93.184.216.34"


def resolves_public(host: str) -> list[str]:
    return [PUBLIC_IP]


def _parry_handler(
    *,
    status: int,
    body: dict | None = None,
    captured: dict | None = None,
):
    def _handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["last_url"] = str(request.url)
            captured["last_body"] = json.loads(request.content.decode() or "{}")
        return httpx.Response(
            status,
            json=body or {},
            headers={"Content-Type": "application/json"},
        )

    return _handler


@pytest.fixture
def patch_httpx(monkeypatch):
    """Replace httpx.AsyncClient() construction inside client.py."""

    def _apply(handler):
        real_transport = httpx.MockTransport(handler)

        original_init = httpx.AsyncClient.__init__

        def new_init(self, *args, **kwargs):
            kwargs["transport"] = real_transport
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", new_init)

    return _apply


@pytest.fixture(autouse=True)
def _no_env_proxies(monkeypatch):
    """Remote constructors refuse to run when an HTTP(S) proxy applies
    (pinning bypasses it). Pin the proxy lookup to "none" so the suite
    doesn't depend on the machine's environment; the proxy tests below
    override it.
    """
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.proxy_bypass", lambda host: False)


def _fake_client(fake_manifest: dict, **overrides):
    kwargs = {
        "agent_id": "dev-assistant",
        "api_key": "sk-parry-test",
    }
    kwargs.update(overrides)
    client = SentinelMCPClient.stdio(command="fake", args=[], **kwargs)
    client._fake_manifest = fake_manifest
    return client


async def test_clean_manifest_connects_ok(patch_httpx) -> None:
    captured: dict = {}
    patch_httpx(
        _parry_handler(
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
    )
    manifest = {
        "tools": [{"name": "read_file", "description": "Reads a file"}]
    }
    client = _fake_client(manifest)
    async with client as c:
        tools = await c.list_tools()
        assert tools["tools"][0]["name"] == "read_file"
        assert c._trust_level == "observed"
    assert captured["last_url"].endswith("/api/v1/mcp/connections")
    assert captured["last_body"]["manifest"] == manifest


async def test_critical_detection_raises_blocked(patch_httpx) -> None:
    patch_httpx(
        _parry_handler(
            status=200,
            body={
                "server_id": "srv-1",
                "trust_level": "suspicious",
                "manifest_changed": False,
                "new_hash": "abc",
                "detections": [
                    {
                        "detector": "mcp_manifest",
                        "severity": "critical",
                        "reason": "Unicode smuggling in tool description",
                        "confidence": 0.95,
                    }
                ],
            },
        )
    )
    manifest = {"tools": [{"name": "read_file", "description": "Reads\u200b a file"}]}
    client = _fake_client(manifest)
    with pytest.raises(MCPBlockedError) as exc:
        async with client:
            pass
    assert "Unicode" in exc.value.reason


async def test_403_raises_blocked(patch_httpx) -> None:
    patch_httpx(_parry_handler(status=403, body={"detail": "blocked"}))
    client = _fake_client({"tools": []})
    with pytest.raises(MCPBlockedError):
        async with client:
            pass


async def test_blocking_false_suppresses_raise(patch_httpx) -> None:
    patch_httpx(
        _parry_handler(
            status=200,
            body={
                "server_id": "srv-1",
                "trust_level": "suspicious",
                "manifest_changed": False,
                "new_hash": "abc",
                "detections": [
                    {
                        "detector": "mcp_manifest",
                        "severity": "critical",
                        "reason": "x",
                        "confidence": 0.9,
                    }
                ],
            },
        )
    )
    client = _fake_client({"tools": []}, blocking=False)
    async with client as c:
        assert c._trust_level == "suspicious"


async def test_backend_unreachable_fails_open(monkeypatch) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    original_init = httpx.AsyncClient.__init__

    def new_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_raise)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", new_init)

    client = _fake_client({"tools": [{"name": "t", "description": "d"}]})
    async with client as c:
        # Should connect even though Parry is unreachable — fail open.
        tools = await c.list_tools()
        assert tools["tools"][0]["name"] == "t"


async def test_list_tools_before_connect_raises() -> None:
    client = SentinelMCPClient.stdio(
        command="fake", args=[], agent_id="a", api_key="sk-parry-x"
    )
    with pytest.raises(MCPManifestError):
        await client.list_tools()


# ── Remote transports ────────────────────────────────────────────────


def _remote_client(fake_manifest: dict, transport: str = "http", **overrides):
    kwargs = {"agent_id": "dev-assistant", "api_key": "sk-parry-test"}
    kwargs.update(overrides)
    factory = getattr(SentinelMCPClient, transport)
    client = factory(
        url="https://mcp.example.com/sse", resolver=resolves_public, **kwargs
    )
    client._fake_manifest = fake_manifest
    return client


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


_MANIFEST = {"tools": [{"name": "read_file", "description": "Reads a file"}]}


@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_remote_transport_reports_itself(patch_httpx, transport) -> None:
    captured: dict = {}
    patch_httpx(_ok_handler(captured))
    async with _remote_client(_MANIFEST, transport):
        pass
    assert captured["last_body"]["transport"] == transport
    assert captured["last_body"]["server_uri"] == "https://mcp.example.com/sse"


async def test_stdio_still_reports_stdio(patch_httpx) -> None:
    """The existing transport must not shift under the new field."""
    captured: dict = {}
    patch_httpx(_ok_handler(captured))
    async with _fake_client(_MANIFEST):
        pass
    assert captured["last_body"]["transport"] == "stdio"


async def test_auth_headers_never_reach_parry(patch_httpx) -> None:
    """A bearer token for the MCP server is not Parry's business."""
    captured: dict = {}
    patch_httpx(_ok_handler(captured))
    client = _remote_client(
        _MANIFEST, "http", headers={"Authorization": "Bearer super-secret-token"}
    )
    async with client:
        pass
    body = json.dumps(captured["last_body"])
    assert "super-secret-token" not in body
    assert "Authorization" not in body


async def test_credential_in_url_never_reaches_parry(patch_httpx) -> None:
    captured: dict = {}
    patch_httpx(_ok_handler(captured))
    client = SentinelMCPClient.http(
        url="https://mcp.example.com/sse?api_key=leaked-key",
        agent_id="dev-assistant",
        api_key="sk-parry-test",
        resolver=resolves_public,
    )
    client._fake_manifest = _MANIFEST
    async with client:
        pass
    assert "leaked-key" not in json.dumps(captured["last_body"])


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/mcp",
        "http://mcp.example.com/sse",
        "file:///etc/passwd",
    ],
)
def test_unsafe_urls_fail_at_construction(url) -> None:
    """Refused at the call site, not deep inside the context manager."""
    with pytest.raises(MCPURLError):
        SentinelMCPClient.http(
            url=url, agent_id="a", api_key="sk-parry-test", resolver=resolves_public
        )


def test_private_url_connects_when_opted_in() -> None:
    client = SentinelMCPClient.http(
        url="https://10.0.0.5/mcp",
        agent_id="a",
        api_key="sk-parry-test",
        allow_private=True,
    )
    assert client._transport_kwargs["server_uri"] == "https://10.0.0.5/mcp"


async def test_hash_is_identical_across_transports(patch_httpx) -> None:
    """Transport must not enter the manifest hash.

    Drift detection compares hashes across connections; if moving a
    server from stdio to HTTP changed its hash, every such move would
    look like manifest tampering and downgrade a trusted server.
    """
    bodies: list[dict] = []

    def _collect(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode() or "{}"))
        return httpx.Response(
            200,
            json={
                "server_id": "srv-1",
                "trust_level": "observed",
                "manifest_changed": False,
                "new_hash": "abc",
                "detections": [],
            },
            headers={"Content-Type": "application/json"},
        )

    patch_httpx(_collect)
    async with _fake_client(_MANIFEST):
        pass
    async with _remote_client(_MANIFEST, "http"):
        pass

    assert len(bodies) == 2
    assert bodies[0]["transport"] == "stdio"
    assert bodies[1]["transport"] == "http"
    assert manifest_hash(bodies[0]["manifest"]) == manifest_hash(bodies[1]["manifest"])


async def test_oversized_tool_list_is_refused(patch_httpx) -> None:
    """Fail closed: a manifest this size is not a tool list."""
    patch_httpx(_ok_handler({}))
    huge = {"tools": [{"name": f"t{i}"} for i in range(MAX_MANIFEST_TOOLS + 1)]}
    with pytest.raises(MCPManifestError, match="above the"):
        async with _remote_client(huge, "http"):
            pass


async def test_tool_list_at_the_cap_is_accepted(patch_httpx) -> None:
    captured: dict = {}
    patch_httpx(_ok_handler(captured))
    at_cap = {"tools": [{"name": f"t{i}"} for i in range(MAX_MANIFEST_TOOLS)]}
    async with _remote_client(at_cap, "http"):
        pass
    assert len(captured["last_body"]["manifest"]["tools"]) == MAX_MANIFEST_TOOLS


async def test_oversized_manifest_bytes_are_refused(patch_httpx) -> None:
    """Few tools can still be enormous if the descriptions are."""
    patch_httpx(_ok_handler({}))
    fat = {"tools": [{"name": "t", "description": "x" * (MAX_MANIFEST_CHARS + 1)}]}
    with pytest.raises(MCPManifestError, match="characters"):
        async with _remote_client(fat, "http"):
            pass


# ── Connection pinning (DNS-rebinding) ──────────────────────────────


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


def _record_connects(monkeypatch, refuse: frozenset[str] = frozenset()) -> list[str]:
    """Patch the real network layer to record every host it is asked to
    dial, raising ConnectError for any host in ``refuse``."""
    dialled: list[str] = []

    async def fake_connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        dialled.append(host)
        if host in refuse:
            raise httpcore.ConnectError(f"refused: {host}")
        return object()

    monkeypatch.setattr("httpcore._backends.anyio.AnyIOBackend.connect_tcp", fake_connect_tcp)
    return dialled


class TestPinnedNetworkBackend:
    async def test_connects_to_pinned_address_not_requested_host(self, monkeypatch) -> None:
        dialled = _record_connects(monkeypatch)
        backend = _PinnedNetworkBackend("mcp.example.com", (PUBLIC_IP,))
        await backend.connect_tcp("mcp.example.com", 443)
        assert dialled == [PUBLIC_IP]

    async def test_host_match_is_case_insensitive(self, monkeypatch) -> None:
        dialled = _record_connects(monkeypatch)
        backend = _PinnedNetworkBackend("mcp.example.com", (PUBLIC_IP,))
        await backend.connect_tcp("MCP.Example.COM", 443)
        assert dialled == [PUBLIC_IP]

    async def test_connects_to_pinned_ipv6_address_unbracketed(self, monkeypatch) -> None:
        dialled = _record_connects(monkeypatch)
        backend = _PinnedNetworkBackend("mcp.example.com", ("2001:db8::1",))
        await backend.connect_tcp("mcp.example.com", 443)
        assert dialled == ["2001:db8::1"]

    async def test_falls_back_to_next_pinned_address(self, monkeypatch) -> None:
        # localhost -> ('::1', '127.0.0.1') with a dev server bound to
        # 127.0.0.1 only: the first attempt fails, the second must be tried.
        dialled = _record_connects(monkeypatch, refuse=frozenset({"::1"}))
        backend = _PinnedNetworkBackend("localhost", ("::1", "127.0.0.1"))
        await backend.connect_tcp("localhost", 8000)
        assert dialled == ["::1", "127.0.0.1"]

    async def test_raises_last_error_when_every_pinned_address_fails(self, monkeypatch) -> None:
        dialled = _record_connects(monkeypatch, refuse=frozenset({"::1", "127.0.0.1"}))
        backend = _PinnedNetworkBackend("localhost", ("::1", "127.0.0.1"))
        with pytest.raises(httpcore.ConnectError, match="127.0.0.1"):
            await backend.connect_tcp("localhost", 8000)
        assert dialled == ["::1", "127.0.0.1"]

    async def test_other_hosts_resolve_normally(self, monkeypatch) -> None:
        # e.g. an OAuth authorization server on another domain reached
        # through the same client: never validated, so never pinned.
        dialled = _record_connects(monkeypatch)
        backend = _PinnedNetworkBackend("mcp.example.com", (PUBLIC_IP,))
        await backend.connect_tcp("auth.other-vendor.example", 443)
        assert dialled == ["auth.other-vendor.example"]


class TestNoRedirectClientPinning:
    def test_no_pinning_matches_current_behavior(self) -> None:
        client = _no_redirect_client()
        transport = client._transport
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert not isinstance(transport, _PinnedHTTPTransport)

    def test_pinned_addresses_build_pinned_transport(self) -> None:
        client = _no_redirect_client(pinned_host="mcp.example.com", pinned_addresses=(PUBLIC_IP,))
        transport = client._transport
        assert isinstance(transport, _PinnedHTTPTransport)
        backend = transport._pool._network_backend
        assert isinstance(backend, _PinnedNetworkBackend)
        assert backend._pinned_host == "mcp.example.com"
        assert backend._pinned_addresses == (PUBLIC_IP,)

    def test_pinned_addresses_without_host_is_refused(self) -> None:
        with pytest.raises(ValueError, match="pinned_host"):
            _no_redirect_client(pinned_addresses=(PUBLIC_IP,))

    def test_pinned_transport_still_verifies_tls(self) -> None:
        client = _no_redirect_client(pinned_host="mcp.example.com", pinned_addresses=(PUBLIC_IP,))
        ssl_context = client._transport._pool._ssl_context
        assert ssl_context.verify_mode.name == "CERT_REQUIRED"

    def test_pinned_transport_still_refuses_redirects(self) -> None:
        client = _no_redirect_client(pinned_host="mcp.example.com", pinned_addresses=(PUBLIC_IP,))
        assert client.follow_redirects is False


def _remote(transport: str = "http", url: str = "https://mcp.example.com/mcp", **kwargs):
    factory = SentinelMCPClient.http if transport == "http" else SentinelMCPClient.sse
    return factory(
        url=url,
        agent_id="dev-assistant",
        api_key="sk-parry-test",
        resolver=kwargs.pop("resolver", resolves_public),
        **kwargs,
    )


def test_remote_client_stores_pinned_host_and_addresses() -> None:
    client = _remote()
    assert client._transport_kwargs["pinned_host"] == "mcp.example.com"
    assert client._transport_kwargs["pinned_addresses"] == (PUBLIC_IP,)


def test_pinned_host_matches_what_httpx_dials_for_idn_hosts() -> None:
    # httpx hands connect_tcp the punycode host; if pinned_host kept the
    # unicode spelling, the host gate would never match and pinning
    # would silently switch off.
    client = _remote(url="https://bücher.example/mcp")
    assert client._transport_kwargs["pinned_host"] == "xn--bcher-kva.example"
    assert (
        httpx.URL(client._transport_kwargs["url"]).raw_host.decode("ascii")
        == client._transport_kwargs["pinned_host"]
    )


class _OpenerReachedError(Exception):
    """Raised by the fake transports once they've captured their client."""


async def _run_opener(client: SentinelMCPClient, opener) -> None:
    client._stack = AsyncExitStack()
    try:
        with pytest.raises(_OpenerReachedError):
            await opener(client)
    finally:
        await client._stack.aclose()


class TestRemoteOpenersUsePinnedTransport:
    """Exercise the real openers, not just transport_kwargs: a kwargs-only
    test is what let a broken streamable_http_client call go unnoticed."""

    async def test_http_opener_hands_mcp_a_pinned_client(self, monkeypatch) -> None:
        captured: dict = {}

        @asynccontextmanager
        async def fake_streamable_http_client(url, *, http_client=None, terminate_on_close=True):
            captured["url"] = url
            captured["client"] = http_client
            raise _OpenerReachedError
            yield  # pragma: no cover

        monkeypatch.setattr(
            "mcp.client.streamable_http.streamable_http_client", fake_streamable_http_client
        )
        client = _remote("http", headers={"Authorization": "Bearer t"})
        await _run_opener(client, SentinelMCPClient._open_http_session)

        http_client = captured["client"]
        assert captured["url"] == "https://mcp.example.com/mcp"
        assert isinstance(http_client._transport, _PinnedHTTPTransport)
        assert http_client._transport._pool._network_backend._pinned_addresses == (PUBLIC_IP,)
        assert http_client.follow_redirects is False
        assert http_client.headers["Authorization"] == "Bearer t"

    async def test_sse_opener_hands_mcp_a_pinned_client_factory(self, monkeypatch) -> None:
        captured: dict = {}

        @asynccontextmanager
        async def fake_sse_client(url, headers=None, timeout=5, httpx_client_factory=None, **kw):
            captured["client"] = httpx_client_factory(headers=headers, auth=None, timeout=timeout)
            raise _OpenerReachedError
            yield  # pragma: no cover

        monkeypatch.setattr("mcp.client.sse.sse_client", fake_sse_client)
        client = _remote("sse")
        await _run_opener(client, SentinelMCPClient._open_sse_session)

        http_client = captured["client"]
        assert isinstance(http_client._transport, _PinnedHTTPTransport)
        assert http_client._transport._pool._network_backend._pinned_addresses == (PUBLIC_IP,)
        await http_client.aclose()


class TestEnvProxyConflict:
    """Pinning dials the validated address directly, which silently skips
    any HTTP(S)_PROXY. Refuse up front instead of degrading quietly."""

    @pytest.mark.parametrize("transport", ["http", "sse"])
    def test_active_proxy_refuses_construction(self, monkeypatch, transport) -> None:
        monkeypatch.setattr(
            "urllib.request.getproxies", lambda: {"https": "http://proxy.example.com:8080"}
        )
        with pytest.raises(MCPURLError, match="proxy"):
            _remote(transport)

    def test_all_proxy_also_counts(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "urllib.request.getproxies", lambda: {"all": "socks5://proxy.example.com:1080"}
        )
        with pytest.raises(MCPURLError, match="proxy"):
            _remote()

    def test_proxy_for_other_scheme_does_not_apply(self, monkeypatch) -> None:
        # An http-only proxy is never used for an https URL.
        monkeypatch.setattr(
            "urllib.request.getproxies", lambda: {"http": "http://proxy.example.com:8080"}
        )
        assert _remote()._transport_kwargs["pinned_addresses"] == (PUBLIC_IP,)

    def test_bypassed_host_is_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "urllib.request.getproxies", lambda: {"https": "http://proxy.example.com:8080"}
        )
        monkeypatch.setattr("urllib.request.proxy_bypass", lambda host: host == "mcp.example.com")
        assert _remote()._transport_kwargs["pinned_addresses"] == (PUBLIC_IP,)

    def test_no_proxy_configured_is_allowed(self) -> None:
        assert _remote()._transport_kwargs["pinned_addresses"] == (PUBLIC_IP,)
