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
    embedded = _embedded_v4(ip)
    # Check embedded v4 addresses first (they're the actual routing target).
    # This ensures NAT64 addresses are judged by their wrapped v4, not the reserved wrapper.
    for candidate in (*embedded, ip):
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
