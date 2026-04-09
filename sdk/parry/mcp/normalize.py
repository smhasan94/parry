"""Canonical MCP manifest normalization — client-side copy.

Mirrors ``backend/app/detection/mcp_normalize.py``. Keeping one
implementation on each side is deliberate: the SDK needs to compute
hashes without an import dependency on the backend package. A drift
test in the SDK test suite pins both to the same behaviour.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def normalize_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return unicodedata.normalize("NFC", text).strip()


def _canonical_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _canonical_schema(schema[k]) for k in sorted(schema.keys())}
    if isinstance(schema, list):
        return [_canonical_schema(v) for v in schema]
    if isinstance(schema, str):
        return normalize_text(schema)
    return schema


def canonical_manifest(manifest: dict[str, Any]) -> bytes:
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
    return hashlib.sha256(canonical_manifest(manifest)).hexdigest()
