"""Unit tests for audit_export_service pure helpers.

DB-backed export (``export_audit_log``) is exercised in e2e tests;
here we lock down chain construction, verification, CSV/JSON
rendering, and the ordering contract that makes the chain
reproducible.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime

from app.db.models import AuditLog
from app.services.audit_export_service import (
    GENESIS_HASH,
    _chain,
    _row_hash,
    render_csv,
    render_json,
    verify_chain,
)


def _entry(
    action: str,
    *,
    id_: uuid.UUID | None = None,
    created_at: datetime | None = None,
    details: dict | None = None,
) -> AuditLog:
    return AuditLog(
        id=id_ or uuid.uuid4(),
        org_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        actor_type="user",
        actor_id="clerk_user_1",
        actor_label="alice@example.com",
        action=action,
        resource_type="agent",
        resource_id="agent-1",
        details=details,
        created_at=created_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
    )


# ── Hash determinism ─────────────────────────────────────────────────


def test_row_hash_stable_across_calls() -> None:
    row = {"id": "a", "action": "x", "details": {"k": 1}}
    assert _row_hash("prev", row) == _row_hash("prev", row)


def test_row_hash_changes_when_prev_changes() -> None:
    row = {"id": "a", "action": "x", "details": None}
    assert _row_hash("A", row) != _row_hash("B", row)


def test_row_hash_changes_when_row_changes() -> None:
    assert _row_hash("p", {"id": "a"}) != _row_hash("p", {"id": "b"})


# ── Chain construction ──────────────────────────────────────────────


def test_empty_chain() -> None:
    assert _chain([]) == []


def test_chain_links_prev_hash_to_predecessor() -> None:
    entries = [
        _entry("first"),
        _entry("second", created_at=datetime(2026, 4, 1, 12, 1, 0, tzinfo=UTC)),
        _entry("third", created_at=datetime(2026, 4, 1, 12, 2, 0, tzinfo=UTC)),
    ]
    rows = _chain(entries)
    assert rows[0]["prev_hash"] == GENESIS_HASH
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert rows[2]["prev_hash"] == rows[1]["row_hash"]


def test_chain_is_reproducible_over_same_input() -> None:
    entries = [_entry("a"), _entry("b"), _entry("c")]
    assert _chain(entries) == _chain(entries)


# ── verify_chain ─────────────────────────────────────────────────────


def test_verify_chain_accepts_clean_chain() -> None:
    rows = _chain([_entry("a"), _entry("b"), _entry("c")])
    assert verify_chain(rows) is True


def test_verify_chain_detects_row_tampering() -> None:
    rows = _chain([_entry("a"), _entry("b"), _entry("c")])
    rows[1]["action"] = "tampered"  # mutate a middle row
    assert verify_chain(rows) is False


def test_verify_chain_detects_hash_tampering() -> None:
    rows = _chain([_entry("a"), _entry("b")])
    rows[1]["row_hash"] = "f" * 64
    assert verify_chain(rows) is False


def test_verify_chain_detects_reordering() -> None:
    rows = _chain([_entry("a"), _entry("b"), _entry("c")])
    rows[1], rows[2] = rows[2], rows[1]
    assert verify_chain(rows) is False


def test_verify_chain_empty_is_valid() -> None:
    assert verify_chain([]) is True


# ── CSV rendering ────────────────────────────────────────────────────


def test_render_csv_roundtrip() -> None:
    rows = _chain([_entry("agent.created"), _entry("agent.deleted")])
    body = render_csv(rows)
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    parsed = list(reader)
    assert len(parsed) == 2
    assert parsed[0]["action"] == "agent.created"
    assert parsed[1]["prev_hash"] == parsed[0]["row_hash"]


def test_render_csv_serializes_details_as_json() -> None:
    rows = _chain([_entry("x", details={"before": {"a": 1}, "after": {"a": 2}})])
    body = render_csv(rows)
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    row = next(reader)
    assert json.loads(row["details"]) == {"before": {"a": 1}, "after": {"a": 2}}


def test_render_csv_never_leaks_raw_dict_repr() -> None:
    # Pre-fix we'd see ``{'k': 1}`` in the CSV which breaks quoting.
    rows = _chain([_entry("x", details={"k": 1})])
    body = render_csv(rows).decode("utf-8")
    assert "{'k': 1}" not in body


# ── JSON rendering ───────────────────────────────────────────────────


def test_render_json_payload_shape() -> None:
    rows = _chain([_entry("a")])
    org_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 5, 1, tzinfo=UTC)
    now = datetime(2026, 4, 2, tzinfo=UTC)
    body = render_json(rows, org_id=org_id, start=start, end=end, generated_at=now)
    parsed = json.loads(body)
    assert parsed["schema_version"] == "1.0"
    assert parsed["org_id"] == str(org_id)
    assert parsed["period"]["start"] == start.isoformat()
    assert parsed["entry_count"] == 1
    assert parsed["entries"][0]["prev_hash"] == GENESIS_HASH


def test_render_json_chain_verifies_end_to_end() -> None:
    rows = _chain([_entry("a"), _entry("b"), _entry("c")])
    body = render_json(
        rows,
        org_id=uuid.uuid4(),
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
        generated_at=datetime(2026, 4, 2, tzinfo=UTC),
    )
    parsed = json.loads(body)
    assert verify_chain(parsed["entries"]) is True
