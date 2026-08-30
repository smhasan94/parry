"""Validate and canonicalise MCP server URIs before they are stored.

The backend never dereferences ``server_uri`` — the SDK connects to the
MCP server and posts the manifest here — so this is not an SSRF guard.
It exists for a narrower reason: whatever lands in this column is
durable. It is written to ``mcp_servers``, echoed in the dashboard, and
copied into audit-log payloads.

That makes credentials the real hazard. A URL like
``https://user:token@mcp.example/`` or ``https://mcp.example/?api_key=…``
carries a secret that would be persisted in plaintext and then read back
by anyone with viewer access. Userinfo is rejected outright and the
query and fragment are stripped, so a token cannot ride the URI into
storage even when a caller passes one.

Canonicalisation is the second job: lowercasing the scheme and host and
dropping the default port means one logical server maps to one row
rather than to several near-duplicates that each carry their own trust
level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

# Postgres would take far more, but a URI this long is a payload rather
# than an address, and the column is echoed into audit rows.
MAX_URI_CHARS = 2_048

_REMOTE_SCHEMES = {"http", "https"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


class InvalidServerURIError(ValueError):
    """Raised when a server URI cannot be stored safely."""


Transport = Literal["stdio", "http", "sse"]


@dataclass(frozen=True)
class ParsedServerURI:
    uri: str
    transport: Transport


def validate_mcp_server_uri(raw: str, transport: str | None = None) -> ParsedServerURI:
    """Return the canonical URI and the transport it implies.

    ``stdio://`` passes through unchanged: it names a local command
    rather than a network location, so there is no host to canonicalise
    and no credential convention to strip.
    """
    uri = (raw or "").strip()
    if not uri:
        raise InvalidServerURIError("server_uri must not be empty")
    if len(uri) > MAX_URI_CHARS:
        raise InvalidServerURIError(f"server_uri exceeds {MAX_URI_CHARS} characters")

    if uri.startswith("stdio://"):
        if not uri[len("stdio://") :].strip():
            raise InvalidServerURIError("stdio server_uri must name a command")
        return ParsedServerURI(uri=uri, transport="stdio")

    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if scheme not in _REMOTE_SCHEMES:
        raise InvalidServerURIError(
            f"unsupported server_uri scheme {parts.scheme!r}; expected http, https, or stdio"
        )

    # Reject before touching .hostname: urlsplit happily parses
    # "https://user:pw@host" and a caller reading only the netloc would
    # never see that a secret went past.
    if "@" in parts.netloc:
        raise InvalidServerURIError("server_uri must not embed credentials")

    try:
        port = parts.port
    except ValueError as exc:  # out-of-range or non-numeric port
        raise InvalidServerURIError("server_uri has an invalid port") from exc

    host = parts.hostname
    if not host:
        raise InvalidServerURIError("server_uri must include a host")

    netloc = host.lower()
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"

    # Query and fragment are dropped rather than preserved: they carry
    # no addressing information the registry needs, and they are where
    # an API key would sit.
    canonical = urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))

    derived: Transport = "sse" if transport == "sse" else "http"
    return ParsedServerURI(uri=canonical, transport=derived)
