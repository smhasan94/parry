"""SDK-side manifest normalization. Mirrors backend tests so the
two implementations can never drift."""

from __future__ import annotations

from parry.mcp.normalize import canonical_manifest, manifest_hash, normalize_text


def test_same_tool_order_same_hash() -> None:
    a = {
        "tools": [
            {"name": "read", "description": "r"},
            {"name": "write", "description": "w"},
        ]
    }
    b = {
        "tools": [
            {"name": "write", "description": "w"},
            {"name": "read", "description": "r"},
        ]
    }
    assert manifest_hash(a) == manifest_hash(b)


def test_different_description_different_hash() -> None:
    a = {"tools": [{"name": "t", "description": "d"}]}
    b = {"tools": [{"name": "t", "description": "d2"}]}
    assert manifest_hash(a) != manifest_hash(b)


def test_server_info_version_ignored() -> None:
    a = {"serverInfo": {"version": "1.0"}, "tools": [{"name": "t", "description": "d"}]}
    b = {"serverInfo": {"version": "9.9"}, "tools": [{"name": "t", "description": "d"}]}
    assert manifest_hash(a) == manifest_hash(b)


def test_nfc_equivalence() -> None:
    a = {"tools": [{"name": "t", "description": "caf\u00e9"}]}
    b = {"tools": [{"name": "t", "description": "cafe\u0301"}]}
    assert manifest_hash(a) == manifest_hash(b)


def test_schema_key_order_ignored() -> None:
    a = {
        "tools": [
            {
                "name": "t",
                "description": "d",
                "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
            }
        ]
    }
    b = {
        "tools": [
            {
                "name": "t",
                "description": "d",
                "inputSchema": {"properties": {"x": {"type": "string"}}, "type": "object"},
            }
        ]
    }
    assert manifest_hash(a) == manifest_hash(b)


def test_canonical_manifest_is_bytes() -> None:
    assert isinstance(canonical_manifest({"tools": []}), bytes)


def test_normalize_text_strips() -> None:
    assert normalize_text("  hello  ") == "hello"
    assert normalize_text(None) == ""
