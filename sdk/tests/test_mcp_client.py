"""SentinelMCPClient wrapper tests.

We don't exercise the real MCP stdio transport here — that needs a
subprocess binary and belongs in integration. Instead we use
``sandbox=True`` to skip the underlying MCP session entirely and
inject a fake manifest through the transport kwargs. The httpx round
trip to the Parry backend is stubbed via a MockTransport.
"""

from __future__ import annotations

import json

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


class TestPinnedNetworkBackend:
    async def test_connects_to_pinned_address_not_requested_host(self, monkeypatch) -> None:
        seen: dict = {}

        async def fake_connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None
        ):
            seen["host"] = host
            seen["port"] = port
            return object()

        monkeypatch.setattr("httpcore._backends.anyio.AnyIOBackend.connect_tcp", fake_connect_tcp)
        backend = _PinnedNetworkBackend("93.184.216.34")
        await backend.connect_tcp("mcp.example.com", 443)
        assert seen == {"host": "93.184.216.34", "port": 443}

    async def test_connects_to_pinned_ipv6_address_unbracketed(self, monkeypatch) -> None:
        seen: dict = {}

        async def fake_connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None
        ):
            seen["host"] = host
            return object()

        monkeypatch.setattr("httpcore._backends.anyio.AnyIOBackend.connect_tcp", fake_connect_tcp)
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
