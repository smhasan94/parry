"""MCP server URI validation and canonicalisation.

The stakes here are storage, not fetching: the backend never
dereferences this value, but it does persist it, echo it to the
dashboard, and copy it into audit rows. So the cases that matter most
are the ones where a credential would otherwise be written down.
"""

from __future__ import annotations

import pytest

from app.core.url_guard import MAX_URI_CHARS, InvalidServerURIError, validate_mcp_server_uri


class TestCredentialsNeverReachStorage:
    def test_userinfo_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="credentials"):
            validate_mcp_server_uri("https://user:t0ken@mcp.example.com/sse")

    def test_bare_username_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="credentials"):
            validate_mcp_server_uri("https://admin@mcp.example.com/")

    def test_query_string_is_stripped(self) -> None:
        parsed = validate_mcp_server_uri("https://mcp.example.com/sse?api_key=sk-live-abc123")
        assert parsed.uri == "https://mcp.example.com/sse"
        assert "api_key" not in parsed.uri
        assert "sk-live" not in parsed.uri

    def test_fragment_is_stripped(self) -> None:
        parsed = validate_mcp_server_uri("https://mcp.example.com/sse#token=abc")
        assert parsed.uri == "https://mcp.example.com/sse"


class TestSchemeRules:
    @pytest.mark.parametrize(
        "uri",
        [
            "file:///etc/passwd",
            "gopher://mcp.example.com/",
            "ftp://mcp.example.com/",
            "javascript:alert(1)",
            "mcp.example.com/sse",
        ],
    )
    def test_unsupported_schemes_are_rejected(self, uri: str) -> None:
        with pytest.raises(InvalidServerURIError):
            validate_mcp_server_uri(uri)

    @pytest.mark.parametrize("uri", ["https://mcp.example.com/sse", "http://localhost:3000/mcp"])
    def test_http_schemes_are_accepted(self, uri: str) -> None:
        assert validate_mcp_server_uri(uri).transport in {"http", "sse"}

    def test_missing_host_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="host"):
            validate_mcp_server_uri("https:///sse")


class TestCanonicalisation:
    def test_scheme_and_host_are_lowercased(self) -> None:
        assert (
            validate_mcp_server_uri("HTTPS://MCP.Example.COM/sse").uri
            == "https://mcp.example.com/sse"
        )

    def test_default_port_is_dropped(self) -> None:
        assert validate_mcp_server_uri("https://mcp.example.com:443/sse").uri == (
            "https://mcp.example.com/sse"
        )
        assert validate_mcp_server_uri("http://mcp.example.com:80/x").uri == (
            "http://mcp.example.com/x"
        )

    def test_non_default_port_is_kept(self) -> None:
        assert validate_mcp_server_uri("https://mcp.example.com:8443/sse").uri == (
            "https://mcp.example.com:8443/sse"
        )

    def test_trailing_slash_is_dropped(self) -> None:
        """Otherwise one server registers as two rows with two trust levels."""
        a = validate_mcp_server_uri("https://mcp.example.com/sse/")
        b = validate_mcp_server_uri("https://mcp.example.com/sse")
        assert a.uri == b.uri

    def test_invalid_port_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="port"):
            validate_mcp_server_uri("https://mcp.example.com:99999/sse")


class TestStdioPassthrough:
    def test_stdio_uri_is_preserved_verbatim(self) -> None:
        """No host to canonicalise; the tail is a command line."""
        raw = "stdio://npx -y @modelcontextprotocol/server-filesystem /tmp"
        parsed = validate_mcp_server_uri(raw)
        assert parsed.uri == raw
        assert parsed.transport == "stdio"

    def test_stdio_without_a_command_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="command"):
            validate_mcp_server_uri("stdio://   ")


class TestTransportDerivation:
    def test_remote_uri_defaults_to_http(self) -> None:
        assert validate_mcp_server_uri("https://mcp.example.com/x").transport == "http"

    def test_declared_sse_is_honoured(self) -> None:
        assert validate_mcp_server_uri("https://mcp.example.com/x", "sse").transport == "sse"

    def test_declared_stdio_on_a_remote_uri_does_not_win(self) -> None:
        """The URI is the authority: an https server is not stdio."""
        assert validate_mcp_server_uri("https://mcp.example.com/x", "stdio").transport == "http"


class TestBounds:
    def test_empty_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="empty"):
            validate_mcp_server_uri("")

    def test_whitespace_only_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="empty"):
            validate_mcp_server_uri("   ")

    def test_overlong_uri_is_rejected(self) -> None:
        with pytest.raises(InvalidServerURIError, match="exceeds"):
            validate_mcp_server_uri("https://mcp.example.com/" + "x" * MAX_URI_CHARS)

    def test_uri_at_the_limit_is_accepted(self) -> None:
        base = "https://mcp.example.com/"
        uri = base + "x" * (MAX_URI_CHARS - len(base))
        assert len(validate_mcp_server_uri(uri).uri) <= MAX_URI_CHARS
