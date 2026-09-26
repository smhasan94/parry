"""Decide whether an MCP server URL is safe for this process to fetch.

Unlike the backend's guard, this one really is about SSRF. The SDK runs
inside the customer's own network and is the thing that opens the
connection, so a URL that reaches it inherits the caller's network
position. The realistic path to a hostile URL is an injected
instruction steering an agent into "connect to this MCP server", which
is precisely the class of attack Parry exists to catch.

Three rules carry the weight:

* **Cloud metadata is never reachable.** 169.254.169.254 and its DNS
  equivalents hand out credentials to anyone who asks. No flag turns
  this off, because no legitimate MCP server lives there.
* **Private ranges are opt-in.** Internal MCP servers are a real
  deployment, so ``allow_private=True`` exists — but it has to be typed
  out by the operator rather than inferred.
* **Plaintext is opt-in except on loopback.** Manifests describe tools
  the agent will be permitted to call; served over http:// they are
  trivially rewritten in transit.

The rules are applied to *addresses*, and a URL is reduced to addresses
two ways before they run. Names are resolved, because checking only
URLs written as bare IPs would be theatre — an attacker who can publish
a DNS record points a hostname at 169.254.169.254 and skips the whole
check without needing a redirect or a rebinding race. And IPv6 forms
that carry an IPv4 address inside them are unwrapped, because they
route to the address they carry: ``2002:a9fe:a9fe::1`` reaches the
metadata service while reading as an unremarkable private v6 address.

What counts as reachable is decided positively — an address must be
globally routable — rather than by listing ranges to deny. A deny list
is only ever as current as the last time someone read an RFC, and it
already had a hole: 100.64.0.0/10 (carrier NAT) reports
``is_private`` False and would have sailed through.

Two things are enforced by the caller rather than here. Redirects are
refused by the transport (``follow_redirects=False``), since a validated
host can still answer with a 302 pointing somewhere this function never
saw. And DNS rebinding — a record that changes between this check and
the connection — is closed by connect-time pinning: ``validate_and_pin``
returns every address it checked, and ``SentinelMCPClient``'s remote
transports dial only those for the validated host instead of resolving
the name again (see ``_PinnedNetworkBackend`` in ``client.py``).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .errors import MCPURLError

# Hostnames that resolve to a metadata service on the major clouds.
# Blocked by name as well as by address because DNS is what an attacker
# would use to dodge a literal-IP check.
_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
}

_LOOPBACK_HOSTS = {"localhost", "localhost.localdomain"}

# The well-known NAT64 prefix. An address in it is an IPv4 address with
# a v6 header stapled on, and it routes to that IPv4 address.
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")

MAX_URL_CHARS = 2_048


Resolver = Callable[[str], list[str]]

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _default_resolver(host: str) -> list[str]:
    """Every address ``host`` resolves to, v4 and v6."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _embedded_v4(ip: _IPAddress) -> list[ipaddress.IPv4Address]:
    """The IPv4 addresses an IPv6 address carries inside it.

    Judging only the outer form is not enough: each of these v6
    encodings delivers traffic to the v4 address it wraps, so the
    wrapped address is the one that has to satisfy the rules.
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return []

    found = [addr for addr in (ip.ipv4_mapped, ip.sixtofour) if addr is not None]
    if ip.teredo is not None:
        found.extend(ip.teredo)  # (relay server, client)
    if ip in _NAT64_PREFIX:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF))
    return found


def _refuse(where: str, why: str) -> None:
    raise MCPURLError(f"refusing to connect to {where}: {why}")


def _check_one(ip: _IPAddress, *, where: str, allow_private: bool, allow_loopback: bool) -> None:
    # Unconditional: link-local is where the metadata services live, and
    # allow_private must not become a way to reach them. Same for the
    # addresses that are not endpoints at all.
    if ip.is_link_local:
        _refuse(where, "link-local address (cloud metadata services live here)")

    if ip.is_loopback:
        # Reachable when the URL said so, since local dev is the point.
        # A *name* landing here did not say so, and is how an agent gets
        # steered into whatever else listens on this machine.
        if allow_loopback or allow_private:
            return
        _refuse(
            where,
            "resolves to loopback; pass allow_private=True if you meant a "
            "service on this machine",
        )

    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        _refuse(where, "reserved address")

    if allow_private:
        return

    if ip.is_private:
        _refuse(
            where,
            "private address; pass allow_private=True if this MCP server "
            "really is internal",
        )
    if not ip.is_global:
        _refuse(
            where,
            "not a globally routable address; pass allow_private=True if "
            "this MCP server really is internal",
        )


def _check_address(raw: str, *, host: str, allow_private: bool, allow_loopback: bool) -> None:
    """Apply the address rules to one resolved address and anything it wraps.

    ``host`` is carried through only so the error names what the user
    typed — being told 169.254.169.254 is refused is not much help when
    the URL said ``mcp.vendor.example``.
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:  # pragma: no cover — getaddrinfo returns valid IPs
        return

    where = f"{host} ({raw})" if raw != host else host
    for candidate in (ip, *_embedded_v4(ip)):
        label = where if candidate is ip else f"{where} -> {candidate}"
        _check_one(
            candidate,
            where=label,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
        )


def _addresses_for(host: str, resolver: Resolver | None) -> list[str]:
    """Resolve ``host``, or return it unchanged if it is already an address."""
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass

    # Failing closed here costs nothing real: a host that cannot be
    # resolved cannot be connected to either.
    resolve = resolver or _default_resolver
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise MCPURLError(f"could not resolve MCP server host {host!r}: {exc}") from exc
    if not addresses:
        raise MCPURLError(f"MCP server host {host!r} resolved to no addresses")
    return addresses


@dataclass(frozen=True)
class ValidatedURL:
    """Result of validating a remote MCP server URL.

    ``pinned_addresses`` are every address ``canonical_url``'s host
    resolved to, in resolution order, each checked against every rule in
    this module. Connecting only to these — instead of letting the
    transport resolve the hostname again — is what closes the
    DNS-rebinding gap: there is no second lookup left to race. All of
    them are kept, not just the first, so the transport can fall back
    across them the way a normal connect would (``localhost`` commonly
    resolves to ``::1`` first while dev servers listen on 127.0.0.1
    only). When the URL already named a literal address (IPv4 or IPv6,
    unbracketed), it is the only entry.
    """

    canonical_url: str
    pinned_addresses: tuple[str, ...]


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
    """Like ``validate_server_url``, but also return the addresses to pin.

    Used by ``SentinelMCPClient.http``/``.sse`` so the transport can
    connect only to the exact addresses that were checked, rather than
    letting it re-resolve the hostname at dial time.
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
    # Every entry already passed _check_address above, so keeping the
    # whole list adds nothing unchecked. dict.fromkeys drops duplicates
    # while preserving resolution order.
    return ValidatedURL(
        canonical_url=canonical_url,
        pinned_addresses=tuple(dict.fromkeys(addresses)),
    )
