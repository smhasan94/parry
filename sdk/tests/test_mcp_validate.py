"""SSRF rules for remote MCP server URLs.

The SDK is the process that actually dials the URL, so these are the
rules that stop an injected "connect to this MCP server" instruction
from turning an agent into a probe of its own network.

Every test that uses a hostname injects a resolver. Names are judged by
what they resolve to, so leaving DNS real would make the suite depend
on the network and, worse, would let a lapsed domain quietly change
what these tests assert.
"""

from __future__ import annotations

import pytest

from parry.mcp.errors import MCPManifestError, MCPURLError
from parry.mcp.validate import (
    MAX_URL_CHARS,
    Resolver,
    ValidatedURL,
    validate_and_pin,
    validate_server_url,
)

PUBLIC_IP = "93.184.216.34"


def resolves_to(*addresses: str) -> Resolver:
    return lambda host: list(addresses)


def refuses(exc: type[BaseException] = OSError) -> Resolver:
    def _resolve(host: str) -> list[str]:
        raise exc(f"no such host: {host}")

    return _resolve


public = resolves_to(PUBLIC_IP)


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
            validate_server_url(url, resolver=public)

    def test_allow_private_does_not_open_link_local(self) -> None:
        with pytest.raises(MCPURLError, match="link-local"):
            validate_server_url(
                "http://169.254.169.254/", allow_private=True, allow_insecure=True
            )

    def test_a_name_pointing_at_metadata_is_refused(self) -> None:
        """The whole point of resolving: a DNS record is not a bypass."""
        with pytest.raises(MCPURLError, match="link-local"):
            validate_server_url(
                "https://metadata-proxy.attacker.example/x",
                resolver=resolves_to("169.254.169.254"),
            )

    def test_allow_private_does_not_open_a_name_pointing_at_metadata(self) -> None:
        with pytest.raises(MCPURLError, match="link-local"):
            validate_server_url(
                "https://metadata-proxy.attacker.example/x",
                allow_private=True,
                resolver=resolves_to("169.254.169.254"),
            )


class TestNamesAreJudgedByWhatTheyResolveTo:
    def test_name_pointing_into_a_private_range_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="private"):
            validate_server_url(
                "https://internal.attacker.example/mcp",
                resolver=resolves_to("10.0.0.5"),
            )

    def test_name_pointing_into_a_private_range_may_be_opted_in(self) -> None:
        assert validate_server_url(
            "https://mcp.corp.example/mcp",
            allow_private=True,
            resolver=resolves_to("10.0.0.5"),
        )

    def test_every_resolved_address_is_checked_not_just_the_first(self) -> None:
        """A round-robin record with one hostile answer is hostile."""
        with pytest.raises(MCPURLError, match="link-local"):
            validate_server_url(
                "https://mixed.attacker.example/mcp",
                resolver=resolves_to(PUBLIC_IP, "169.254.169.254"),
            )

    def test_unresolvable_host_fails_closed(self) -> None:
        """Costs nothing real: a name that will not resolve will not dial."""
        with pytest.raises(MCPURLError, match="could not resolve"):
            validate_server_url("https://nope.example/mcp", resolver=refuses())

    def test_host_resolving_to_nothing_fails_closed(self) -> None:
        with pytest.raises(MCPURLError, match="no addresses"):
            validate_server_url("https://nope.example/mcp", resolver=resolves_to())


class TestAddressesThatOnlyLookPublic:
    """Forms that pass a naive is_private check but do not route publicly."""

    def test_cgnat_shared_space_is_refused(self) -> None:
        """100.64.0.0/10 reports is_private False — carrier NAT, not public."""
        with pytest.raises(MCPURLError, match="globally routable"):
            validate_server_url("https://100.64.0.1/mcp")

    def test_cgnat_may_be_opted_in_like_any_other_internal_address(self) -> None:
        assert validate_server_url("https://100.64.0.1/mcp", allow_private=True)

    @pytest.mark.parametrize(
        "host",
        [
            "[::ffff:169.254.169.254]",  # v4-mapped
            "[2002:a9fe:a9fe::1]",  # 6to4
            "[64:ff9b::a9fe:a9fe]",  # NAT64
        ],
    )
    def test_v6_wrappers_around_metadata_are_refused(self, host: str) -> None:
        """Each of these routes to 169.254.169.254 wearing a v6 coat."""
        with pytest.raises(MCPURLError):
            validate_server_url(f"https://{host}/mcp", allow_private=True)

    @pytest.mark.parametrize("host", ["0.0.0.0", "[::]"])
    def test_unspecified_addresses_are_refused(self, host: str) -> None:
        with pytest.raises(MCPURLError):
            validate_server_url(f"https://{host}/mcp", allow_private=True)


class TestPrivateRangesAreOptIn:
    @pytest.mark.parametrize(
        "host", ["10.0.0.5", "172.16.4.1", "192.168.1.10", "[fc00::1]"]
    )
    def test_private_addresses_refused_by_default(self, host: str) -> None:
        with pytest.raises(MCPURLError, match="private"):
            validate_server_url(f"https://{host}/mcp")

    @pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.10", "[fc00::1]"])
    def test_private_addresses_allowed_when_opted_in(self, host: str) -> None:
        assert validate_server_url(f"https://{host}/mcp", allow_private=True)

    def test_public_address_needs_no_flag(self) -> None:
        assert validate_server_url("https://mcp.example.com/sse", resolver=public)


class TestLoopback:
    """Local dev must keep working; a *name* aimed at loopback must not."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:3000/mcp",
            "http://127.0.0.1:3000/mcp",
            "http://[::1]:3000/mcp",
        ],
    )
    def test_loopback_written_as_loopback_is_allowed(self, url: str) -> None:
        assert validate_server_url(url, resolver=resolves_to("127.0.0.1"))

    def test_a_name_resolving_to_loopback_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="loopback"):
            validate_server_url(
                "https://local.attacker.example/mcp",
                resolver=resolves_to("127.0.0.1"),
            )

    def test_a_name_resolving_to_loopback_may_be_opted_in(self) -> None:
        assert validate_server_url(
            "https://local.attacker.example/mcp",
            allow_private=True,
            resolver=resolves_to("127.0.0.1"),
        )


class TestPlaintextRules:
    def test_http_to_a_public_host_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="plaintext"):
            validate_server_url("http://mcp.example.com/sse", resolver=public)

    def test_http_to_loopback_is_allowed_for_local_dev(self) -> None:
        assert validate_server_url("http://localhost:3000/mcp", resolver=public)
        assert validate_server_url("http://127.0.0.1:3000/mcp")

    def test_http_allowed_when_explicitly_opted_in(self) -> None:
        assert validate_server_url(
            "http://mcp.example.com/sse", allow_insecure=True, resolver=public
        )

    def test_https_is_always_fine(self) -> None:
        assert validate_server_url("https://mcp.example.com/sse", resolver=public)


class TestCredentialsAndSchemes:
    def test_userinfo_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="credentials"):
            validate_server_url("https://user:token@mcp.example.com/sse")

    def test_query_and_fragment_are_dropped(self) -> None:
        got = validate_server_url(
            "https://mcp.example.com/sse?api_key=secret#frag", resolver=public
        )
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
            validate_server_url("HTTPS://MCP.Example.COM:443/sse/", resolver=public)
            == "https://mcp.example.com/sse"
        )

    def test_non_default_port_survives(self) -> None:
        assert (
            validate_server_url("https://mcp.example.com:8443/sse", resolver=public)
            == "https://mcp.example.com:8443/sse"
        )

    def test_v6_literal_keeps_its_brackets(self) -> None:
        """Unbracketed, the port delimiter is ambiguous and the URL is junk."""
        assert (
            validate_server_url("https://[fc00::1]:8443/mcp", allow_private=True)
            == "https://[fc00::1]:8443/mcp"
        )

    def test_overlong_url_is_refused(self) -> None:
        with pytest.raises(MCPURLError, match="exceeds"):
            validate_server_url("https://mcp.example.com/" + "x" * MAX_URL_CHARS)


def test_url_error_is_catchable_as_manifest_error() -> None:
    """Existing callers handle MCPManifestError; they must keep working."""
    with pytest.raises(MCPManifestError):
        validate_server_url("file:///etc/passwd")


class TestValidateAndPin:
    """validate_and_pin returns the same canonical URL as validate_server_url,
    plus every address that was actually checked — the ones connect-time
    pinning (client.py) will dial instead of letting the transport re-resolve.
    """

    def test_returns_canonical_url_and_pinned_addresses(self) -> None:
        result = validate_and_pin(
            "https://mcp.example.com/mcp/", resolver=resolves_to(PUBLIC_IP)
        )
        assert result == ValidatedURL(
            canonical_url="https://mcp.example.com/mcp",
            pinned_addresses=(PUBLIC_IP,),
        )

    def test_pins_every_resolved_address_in_resolution_order(self) -> None:
        # All of them, not just the first: the transport falls back
        # across them at connect time, as a normal connect would.
        second_public = "93.184.216.35"
        result = validate_and_pin(
            "https://mcp.example.com/mcp",
            resolver=resolves_to(PUBLIC_IP, second_public),
        )
        assert result.pinned_addresses == (PUBLIC_IP, second_public)

    def test_duplicate_resolved_addresses_are_pinned_once(self) -> None:
        result = validate_and_pin(
            "https://mcp.example.com/mcp",
            resolver=resolves_to(PUBLIC_IP, PUBLIC_IP),
        )
        assert result.pinned_addresses == (PUBLIC_IP,)

    def test_one_unsafe_address_among_several_refuses_the_url(self) -> None:
        # Pinning the whole list is only safe because every entry was
        # checked — a single bad one must still refuse the URL outright.
        with pytest.raises(MCPURLError):
            validate_and_pin(
                "https://mcp.example.com/mcp",
                resolver=resolves_to(PUBLIC_IP, "169.254.169.254"),
            )

    def test_pins_ipv6_literal_unbracketed(self) -> None:
        # A bare IPv6 literal in the URL is already an address — no
        # resolver call — and must come back without brackets, since
        # that's what anyio.connect_tcp expects as remote_host.
        #
        # NOTE: the brief's original example used 2001:db8::1 (the IANA
        # *documentation* prefix). Python's ipaddress module classifies
        # that whole /32 as is_private=True (and is_global=False), so it
        # is refused by the existing, unchanged private-address rule —
        # not something this refactor touches. Swapped for a real
        # globally-routable v6 literal (Cloudflare DNS) so the test
        # actually exercises "bare v6 literal, no resolver, unbracketed"
        # without needing allow_private=True.
        result = validate_and_pin("https://[2606:4700:4700::1111]/mcp")
        assert result.pinned_addresses == ("2606:4700:4700::1111",)

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
