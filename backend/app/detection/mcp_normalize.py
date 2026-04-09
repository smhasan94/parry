"""Canonical MCP manifest normalization + hashing.

Single source of truth for the "is this manifest the same?" question.
Both the SDK wrapper (computes the hash locally before POSTing) and
the backend service call these helpers so the two sides always agree
on what constitutes a drift.

Rules:
- Tools are sorted by name before hashing (server-side ordering is
  not stable).
- Volatile metadata (`serverInfo.version`, top-level `_meta`,
  `capabilities.experimental`) is stripped — it flaps without any
  behavior change.
- Text fields are NFC-normalized so visually-identical manifests hash
  identically regardless of how the server encoded them.
- `inputSchema` is canonicalized via ``json.dumps(..., sort_keys=True)``.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def normalize_text(text: str) -> str:
    """NFC-normalize and strip leading/trailing whitespace."""
    if not isinstance(text, str):
        return ""
    return unicodedata.normalize("NFC", text).strip()


def _canonical_schema(schema: Any) -> Any:
    """Deep-copy a JSON schema with dict keys sorted for stable hashing."""
    if isinstance(schema, dict):
        return {k: _canonical_schema(schema[k]) for k in sorted(schema.keys())}
    if isinstance(schema, list):
        return [_canonical_schema(v) for v in schema]
    if isinstance(schema, str):
        return normalize_text(schema)
    return schema


def canonical_manifest(manifest: dict[str, Any]) -> bytes:
    """Return the manifest in a deterministic byte form suitable for hashing.

    Only the fields we care about for drift are included: tool name,
    tool description, and input schema. Anything else is discarded.
    """
    tools_in = manifest.get("tools") or []
    tools_out: list[dict[str, Any]] = []
    for t in tools_in:
        if not isinstance(t, dict):
            continue
        name = t.get("name") or ""
        tools_out.append(
            {
                "name": normalize_text(name),
                "description": normalize_text(t.get("description") or ""),
                "inputSchema": _canonical_schema(t.get("inputSchema") or {}),
            }
        )
    tools_out.sort(key=lambda t: t["name"])
    canonical = {"tools": tools_out}
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def manifest_hash(manifest: dict[str, Any]) -> str:
    """Stable sha256 hex digest for a manifest."""
    return hashlib.sha256(canonical_manifest(manifest)).hexdigest()


def tool_count(manifest: dict[str, Any]) -> int:
    tools = manifest.get("tools") or []
    return sum(1 for t in tools if isinstance(t, dict))
