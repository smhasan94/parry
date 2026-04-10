"""Audit log service — append-only record of who did what."""

import uuid
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

log = structlog.get_logger()


async def log_action(
    db: AsyncSession,
    org_id: uuid.UUID,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    actor_label: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    obligation_ids: list[str] | None = None,
) -> AuditLog:
    """Append an entry to the audit log.

    The caller is responsible for committing the transaction. This keeps audit
    writes atomic with the action being logged (e.g., incident status update).

    ``obligation_ids``: optional list of EU AI Act obligation references
    (e.g. ["art_26_6_usage_logs"]) to tag this entry for compliance reporting.
    Stored inside ``details`` under the ``_obligation_ids`` key.
    """
    if obligation_ids:
        details = {**(details or {}), "_obligation_ids": obligation_ids}

    entry = AuditLog(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    db.add(entry)
    await db.flush()
    log.info(
        "audit.logged",
        action=action,
        actor=actor_label or actor_id or actor_type,
        resource=f"{resource_type}:{resource_id}" if resource_type else None,
    )
    return entry


async def list_audit_log(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[AuditLog], str | None]:
    """Cursor-paginated audit log query, newest first."""
    query = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
    )

    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
            cursor_entry = await db.get(AuditLog, cursor_id)
            if cursor_entry:
                query = query.where(AuditLog.created_at < cursor_entry.created_at)
        except ValueError:
            pass

    query = query.limit(limit + 1)
    result = await db.execute(query)
    entries = list(result.scalars().all())

    next_cursor = None
    if len(entries) > limit:
        entries = entries[:limit]
        next_cursor = str(entries[-1].id)

    return entries, next_cursor
