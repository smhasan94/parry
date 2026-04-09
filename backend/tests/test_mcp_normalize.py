"""Hash stability properties for canonical MCP manifests."""

from __future__ import annotations

from app.detection.mcp_normalize import (
    canonical_manifest,
    manifest_hash,
    normalize_text,
    tool_count,
)


def test_same_tool_order_same_hash() -> None:
    a = {
        "tools": [
            {"name": "read_file", "description": "Reads a file"},
            {"name": "write_file", "description": "Writes a file"},
        ]
    }
    b = {
        "tools": [
            {"name": "write_file", "description": "Writes a file"},
            {"name": "read_file", "description": "Reads a file"},
        ]
    }
    assert manifest_hash(a) == manifest_hash(b)


def test_different_description_different_hash() -> None:
    a = {"tools": [{"name": "read_file", "description": "Reads a file"}]}
    b = {"tools": [{"name": "read_file", "description": "Reads a file safely"}]}
    assert manifest_hash(a) != manifest_hash(b)


def test_different_schema_different_hash() -> None:
    a = {
        "tools": [
            {
                "name": "read",
                "description": "d",
                "inputSchema": {"properties": {"path": {"type": "string"}}},
            }
        ]
    }
    b = {
        "tools": [
            {
                "name": "read",
                "description": "d",
                "inputSchema": {
                    "properties": {"path": {"type": "string"}, "encoding": {"type": "string"}}
                },
            }
        ]
    }
    assert manifest_hash(a) != manifest_hash(b)


def test_server_info_version_ignored() -> None:
    a = {
        "serverInfo": {"version": "1.0.0"},
        "tools": [{"name": "x", "description": "y"}],
    }
    b = {
        "serverInfo": {"version": "9.9.9"},
        "_meta": {"x": "y"},
        "tools": [{"name": "x", "description": "y"}],
    }
    assert manifest_hash(a) == manifest_hash(b)


def test_schema_key_order_ignored() -> None:
    a = {
        "tools": [
            {
                "name": "t",
                "description": "d",
                "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}},
            }
        ]
    }
    b = {
        "tools": [
            {
                "name": "t",
                "description": "d",
                "inputSchema": {"properties": {"a": {"type": "string"}}, "type": "object"},
            }
        ]
    }
    assert manifest_hash(a) == manifest_hash(b)


def test_nfc_equivalence() -> None:
    # "é" can be encoded as U+00E9 or U+0065 U+0301; NFC collapses them.
    a = {"tools": [{"name": "t", "description": "caf\u00e9"}]}
    b = {"tools": [{"name": "t", "description": "cafe\u0301"}]}
    assert manifest_hash(a) == manifest_hash(b)


def test_empty_manifest() -> None:
    assert manifest_hash({}) == manifest_hash({"tools": []})
    assert tool_count({}) == 0


def test_normalize_text() -> None:
    assert normalize_text("  hello  ") == "hello"
    assert normalize_text(None) == ""  # type: ignore[arg-type]


def test_canonical_manifest_is_bytes() -> None:
    result = canonical_manifest({"tools": [{"name": "x"}]})
    assert isinstance(result, bytes)
    assert b'"x"' in result


def test_tool_count_counts_only_dicts() -> None:
    manifest = {"tools": [{"name": "a"}, "not a dict", {"name": "b"}]}
    assert tool_count(manifest) == 2
