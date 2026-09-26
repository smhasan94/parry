"""Address-based SSRF checks for customer-supplied outbound URLs.

Mirrors sdk/tests/test_mcp_validate.py's approach: every test that
needs a hostname injects a resolver so the suite never touches the
network, and every address-form test uses a literal IP so it needs
no resolver at all.
"""

from __future__ import annotations

import threading

import pytest

from app.core.url_safety import (
    Resolver,
    UnsafeURLError,
    assert_public_https_url,
    assert_public_https_url_async,
)


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


class TestAsyncWrapper:
    """``assert_public_https_url`` resolves DNS synchronously. Called directly
    from a coroutine on uvicorn's loop, a slow nameserver for a customer's
    domain would stall every request on that worker, so async callers go
    through ``assert_public_https_url_async``, which runs it in a thread."""

    @pytest.mark.asyncio
    async def test_resolves_off_the_event_loop_thread(self) -> None:
        loop_thread = threading.get_ident()
        seen: list[int] = []

        def _record(host: str) -> list[str]:
            seen.append(threading.get_ident())
            return [PUBLIC_IP]

        await assert_public_https_url_async("https://hooks.example/hook", resolver=_record)

        assert seen, "resolver was never called"
        assert all(thread != loop_thread for thread in seen)

    @pytest.mark.asyncio
    async def test_raises_for_an_unsafe_url(self) -> None:
        with pytest.raises(UnsafeURLError, match="link-local"):
            await assert_public_https_url_async("https://169.254.169.254/hook")
