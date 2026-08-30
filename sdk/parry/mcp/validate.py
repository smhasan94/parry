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

Redirects are refused by the caller (``follow_redirects=False``) rather
than here, since a validated host can still answer with a 302 pointing
somewhere this function never saw.
"""

from __future__ import annotations

import ipaddress
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

MAX_URL_CHARS = 2_048


def _is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_server_url(
    url: str,
    *,
    allow_insecure: bool = False,
    allow_private: bool = False,
) -> str:
    """Return the canonical URL, or raise ``MCPURLError``.

    Canonical form drops the query and fragment: an MCP endpoint is
    addressed by scheme, host and path, and those two fields are where
    a token would sit. Dropping them here means the value handed to the
    backend cannot carry a credential even by accident.
    """
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

    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        # Unconditional: link-local is where the metadata services live,
        # and allow_private must not become a way to reach them.
        if ip.is_link_local:
            raise MCPURLError(
                f"refusing to connect to link-local address {host} "
                "(cloud metadata services live here)"
            )
        if ip.is_reserved or ip.is_multicast:
            raise MCPURLError(f"refusing to connect to reserved address {host}")
        if ip.is_private and not ip.is_loopback and not allow_private:
            raise MCPURLError(
                f"{host} is a private address; pass allow_private=True if this "
                "MCP server really is internal"
            )

    if scheme == "http" and not is_loopback and not allow_insecure:
        raise MCPURLError(
            f"refusing to fetch an MCP manifest over plaintext http from {host}; "
            "use https, or pass allow_insecure=True if you accept the risk"
        )

    netloc = host
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"

    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))
