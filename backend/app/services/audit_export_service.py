"""SOC 2-style audit log export.

Produces either CSV or JSON exports of an org's audit log over a date
window, with a tamper-evident hash chain appended to each row so an
auditor (or a future you) can prove the export hasn't been edited.

Chain construction (per export):

    row_hash_n = sha256(prev_hash_{n-1} + canonical_json(row_n))
    prev_hash_0 = "GENESIS"

Rows are ordered by ``created_at ASC, id ASC`` so the chain is
reproducible — re-running the export over the same range produces
the same hashes. The chain is **per-export**, not persisted in the
table, because the ``audit_log`` table is append-only from application
code (not tamper-proof at the DB layer) and the goal here is to give
the auditor a self-contained artefact they can verify offline.

Hash verification is in ``verify_chain`` and the monthly S3 task +
the admin-triggered route both consume the same functions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

log = structlog.get_logger()

GENESIS_HASH = "GENESIS"

CSV_COLUMNS = [
    "id",
    "created_at",
    "org_id",
    "actor_type",
    "actor_id",
    "actor_label",
    "action",
    "resource_type",
    "resource_id",
    "details",
    "prev_hash",
    "row_hash",
]


def _canonical_row(entry: AuditLog) -> dict[str, Any]:
    """Stable dict representation for hashing.

    Keys are sorted (via ``json.dumps(sort_keys=True)`` downstream) so
    the hash is identical across Python runs. ``details`` is carried
    through verbatim — the caller persisted the exact JSON the
    auditor will re-hash.
    """
    return {
        "id": str(entry.id),
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "org_id": str(entry.org_id),
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "actor_label": entry.actor_label,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "details": entry.details,
    }


def _row_hash(prev_hash: str, row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(b"\n")
    digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


async def _fetch_entries(
    db: AsyncSession,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.org_id == org_id,
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        )
        # Deterministic ordering is load-bearing: the chain must be
        # reproducible, so the sort key can't depend on insertion
        # races with identical timestamps.
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _chain(entries: Iterable[AuditLog]) -> list[dict[str, Any]]:
    """Walk the entries and attach prev_hash + row_hash to each.

    Pure function — takes already-fetched rows so tests can hand it
    synthetic data without touching a DB.
    """
    prev = GENESIS_HASH
    chained: list[dict[str, Any]] = []
    for entry in entries:
        row = _canonical_row(entry)
        h = _row_hash(prev, row)
        row["prev_hash"] = prev
        row["row_hash"] = h
        chained.append(row)
        prev = h
    return chained


def render_csv(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL
    )
    writer.writeheader()
    for row in rows:
        serialized = dict(row)
        # CSV can't carry nested JSON — stringify the details column
        # with the same canonical serialisation used for hashing so
        # auditors can re-hash directly from the CSV.
        if serialized.get("details") is not None:
            serialized["details"] = json.dumps(
                serialized["details"], sort_keys=True, separators=(",", ":"), default=str
            )
        writer.writerow(serialized)
    return buf.getvalue().encode("utf-8")


def render_json(
    rows: list[dict[str, Any]],
    *,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
    generated_at: datetime,
) -> bytes:
    payload = {
        "schema_version": "1.0",
        "org_id": str(org_id),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": generated_at.isoformat(),
        "chain_algorithm": "sha256(prev_hash + \\n + canonical_json(row))",
        "genesis_hash": GENESIS_HASH,
        "entry_count": len(rows),
        "entries": rows,
    }
    return json.dumps(payload, indent=2, default=str, sort_keys=False).encode("utf-8")


async def export_audit_log(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    fmt: str = "csv",
    generated_at: datetime,
) -> tuple[bytes, int, str]:
    """Build the export artefact.

    Returns ``(bytes, entry_count, final_row_hash)``. Final hash is
    the tip of the chain — useful to log alongside the export action
    so a tampering attempt on the artefact can be detected later.
    """
    if end <= start:
        raise ValueError("end must be after start")
    if fmt not in ("csv", "json"):
        raise ValueError(f"Unsupported export format: {fmt}")

    entries = await _fetch_entries(db, org_id, start, end)
    rows = _chain(entries)
    final_hash = rows[-1]["row_hash"] if rows else GENESIS_HASH

    if fmt == "csv":
        body = render_csv(rows)
    else:
        body = render_json(
            rows,
            org_id=org_id,
            start=start,
            end=end,
            generated_at=generated_at,
        )

    log.info(
        "audit.export_built",
        org_id=str(org_id),
        format=fmt,
        entry_count=len(rows),
        final_hash=final_hash,
        bytes=len(body),
    )
    return body, len(rows), final_hash


def verify_chain(rows: list[dict[str, Any]]) -> bool:
    """Re-walk the chain and confirm every row_hash is correct.

    Accepts the same dict shape ``_chain`` produces (with prev_hash
    and row_hash already attached). Used by tests; also the recipe
    auditors run offline against an exported JSON file.
    """
    prev = GENESIS_HASH
    for row in rows:
        clean = {k: v for k, v in row.items() if k not in ("prev_hash", "row_hash")}
        expected = _row_hash(prev, clean)
        if row.get("prev_hash") != prev:
            return False
        if row.get("row_hash") != expected:
            return False
        prev = expected
    return True
