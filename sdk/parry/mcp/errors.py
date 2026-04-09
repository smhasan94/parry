"""Exceptions raised by the Parry MCP wrapper."""

from __future__ import annotations

from typing import Any


class MCPBlockedError(Exception):
    """Raised when Parry's backend blocks an MCP server or tool call.

    Attributes:
        reason: Human-readable reason string.
        detections: List of Parry detection dicts, if any.
        server_uri: The URI of the server that was blocked.
    """

    def __init__(
        self,
        reason: str,
        *,
        detections: list[dict[str, Any]] | None = None,
        server_uri: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detections = detections or []
        self.server_uri = server_uri


class MCPManifestError(Exception):
    """Raised when the manifest is structurally invalid or can't be fetched."""
