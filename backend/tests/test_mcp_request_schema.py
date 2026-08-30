"""Boundary validation on POST /mcp/connections.

The request model is where a credential-bearing URI has to die, so
these run against the schema directly rather than through the route —
no database required, and the assertions land on the exact value that
would otherwise be persisted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.mcp import MAX_MANIFEST_TOOLS, MCPConnectionRequest

_MANIFEST = {"tools": [{"name": "search", "description": "Search the web"}]}


def _request(**over):
    body = {
        "agent_id": "support-bot",
        "server_uri": "https://mcp.example.com/sse",
        "manifest": _MANIFEST,
    }
    body.update(over)
    return MCPConnectionRequest(**body)


class TestBackwardCompatibility:
    def test_legacy_stdio_payload_without_transport_still_validates(self) -> None:
        """Older SDKs send no transport field at all."""
        req = _request(server_uri="stdio://npx -y @scope/server", transport=None)
        assert req.transport == "stdio"
        assert req.server_uri == "stdio://npx -y @scope/server"

    def test_remote_uri_without_transport_derives_http(self) -> None:
        assert _request().transport == "http"

    def test_declared_sse_is_preserved(self) -> None:
        assert _request(transport="sse").transport == "sse"


class TestCredentialsAreRefusedAtTheBoundary:
    def test_userinfo_uri_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="credentials"):
            _request(server_uri="https://user:t0ken@mcp.example.com/sse")

    def test_token_in_query_never_survives_validation(self) -> None:
        req = _request(server_uri="https://mcp.example.com/sse?api_key=sk-live-secret")
        assert req.server_uri == "https://mcp.example.com/sse"
        assert "sk-live-secret" not in req.server_uri


class TestRejectedUris:
    @pytest.mark.parametrize(
        "uri",
        ["file:///etc/passwd", "ftp://mcp.example.com/", "", "not-a-uri"],
    )
    def test_unusable_uris_are_rejected(self, uri: str) -> None:
        with pytest.raises(ValidationError):
            _request(server_uri=uri)


class TestManifestBounds:
    def test_manifest_over_the_tool_cap_is_rejected(self) -> None:
        oversized = {"tools": [{"name": f"t{i}"} for i in range(MAX_MANIFEST_TOOLS + 1)]}
        with pytest.raises(ValidationError, match="more than"):
            _request(manifest=oversized)

    def test_manifest_at_the_cap_is_accepted(self) -> None:
        at_cap = {"tools": [{"name": f"t{i}"} for i in range(MAX_MANIFEST_TOOLS)]}
        assert len(_request(manifest=at_cap).manifest["tools"]) == MAX_MANIFEST_TOOLS

    def test_manifest_without_a_tools_list_is_left_alone(self) -> None:
        """Shape validation belongs to the detector, not the size cap."""
        assert _request(manifest={}).manifest == {}
