"""SSRF rules for remote MCP server URLs.

The SDK is the process that actually dials the URL, so these are the
rules that stop an injected "connect to this MCP server" instruction
from turning an agent into a probe of its own network.
"""

from __future__ import annotations

import pytest

from parry.mcp.errors import MCPManifestError, MCPURLError
from parry.mcp.validate import MAX_URL_CHARS, validate_server_url


class TestCloudMetadataIsNeverReachable:
    """No flag may open these — there is no legitimate server here."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://169.254.169.254/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/",
        ],
    )
    def test_metadata_endpoints_are_refused(self, url: str) -> None:
        with pytest.raises(MCPURLError):
            validate_server_url(url)

    def test_allow_private_does_not_open_link_local(self) -> None:
        with pytest.raises(MCPURLError, match="link-local"):
            validate_server_url(
                "http://169.254.169.254/", allow_private=True, allow_insecure=True
            )


class TestPrivateRangesAreOptIn:
    @pytest.mark.parametrize(
        "host", ["10.0.0.5", "172.16.4.1", "192.168.1.10", "[fc00::1]"]
    )
    def test_private_addresses_refused_by_default(self, host: str) -> None:
        with pytest.raises(MCPURLError, match="private"):
            validate_server_url(f"https://{host}/mcp")

    @pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.10"])
    def test_private_addresses_allowed_when_opted_in(self, host: str) -> None:
        assert validate_server_url(f"https://{host}/mcp", allow_private=True)

    def test_public_address_needs_no_flag(self) -> None:
        assert validate_server_url("https://mcp.example.com/sse")


class TestPlaintextRules:
    def test_http_to_a_public_host_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="plaintext"):
            validate_server_url("http://mcp.example.com/sse")

    def test_http_to_loopback_is_allowed_for_local_dev(self) -> None:
        assert validate_server_url("http://localhost:3000/mcp")
        assert validate_server_url("http://127.0.0.1:3000/mcp")

    def test_http_allowed_when_explicitly_opted_in(self) -> None:
        assert validate_server_url("http://mcp.example.com/sse", allow_insecure=True)

    def test_https_is_always_fine(self) -> None:
        assert validate_server_url("https://mcp.example.com/sse")


class TestCredentialsAndSchemes:
    def test_userinfo_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="credentials"):
            validate_server_url("https://user:token@mcp.example.com/sse")

    def test_query_and_fragment_are_dropped(self) -> None:
        got = validate_server_url("https://mcp.example.com/sse?api_key=secret#frag")
        assert got == "https://mcp.example.com/sse"
        assert "secret" not in got

    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "gopher://x/", "ftp://x/", "stdio://npx foo", ""]
    )
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        with pytest.raises(MCPURLError):
            validate_server_url(url)


class TestCanonicalisation:
    def test_host_is_lowercased_and_default_port_dropped(self) -> None:
        assert (
            validate_server_url("HTTPS://MCP.Example.COM:443/sse/")
            == "https://mcp.example.com/sse"
        )

    def test_non_default_port_survives(self) -> None:
        assert (
            validate_server_url("https://mcp.example.com:8443/sse")
            == "https://mcp.example.com:8443/sse"
        )

    def test_overlong_url_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="exceeds"):
            validate_server_url("https://mcp.example.com/" + "x" * MAX_URL_CHARS)


def test_url_error_is_catchable_as_manifest_error() -> None:
    """Existing callers handle MCPManifestError; they must keep working."""
    with pytest.raises(MCPManifestError):
        validate_server_url("file:///etc/passwd")
