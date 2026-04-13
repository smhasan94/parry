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
import pytest

from parry.mcp import MCPBlockedError, SentinelMCPClient
from parry.mcp.errors import MCPManifestError


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
