"""MCP server registry + trust lifecycle.

Single source of truth for "is this MCP server known, and do we
trust it?". Called by:

- `POST /api/v1/mcp/connections` on every SDK connect
- `PATCH /api/v1/mcp/servers/{id}` when an admin changes trust level
- Dashboard list/detail endpoints

Drift detection:
- On insert, `trust_level='observed'`, hash_history has one entry.
- On update with the same hash, bump `last_seen_at`.
- On update with a different hash: append to `hash_history`, and if
  the previous trust level was `'trusted'`, downgrade to `'observed'`
  so an admin has to re-approve before the SDK treats it as safe.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import MCPServer
from app.detection.mcp_normalize import manifest_hash, tool_count

log = structlog.get_logger()

_VALID_TRUST_LEVELS = {"observed", "trusted", "suspicious", "blocked"}
_HASH_HISTORY_MAX = 50


class MCPServerBlockedError(Exception):
    """Raised by the API when an SDK connects to a blocked server."""


async def upsert_server(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    server_uri: str,
    server_name: str | None,
    manifest: dict[str, Any],
) -> tuple[MCPServer, bool, str | None]:
    """Register or refresh an MCP server.

    Returns ``(server, manifest_changed, previous_trust_level)``.
    ``previous_trust_level`` is set only when a trusted server had
    its manifest change and got auto-downgraded.
    """
    new_hash = manifest_hash(manifest)
    count = tool_count(manifest)

    existing = (
        await db.execute(
            select(MCPServer).where(
                MCPServer.org_id == org_id,
                MCPServer.server_uri == server_uri,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)

    if existing is None:
        server = MCPServer(
            org_id=org_id,
            server_uri=server_uri,
            server_name=server_name,
            manifest=manifest,
            manifest_hash=new_hash,
            tool_count=count,
            trust_level="observed",
            reputation=50,
            hash_history=[{"hash": new_hash, "seen_at": now.isoformat()}],
        )
        db.add(server)
        await db.flush()
        log.info(
            "mcp.server_registered",
            org_id=str(org_id),
            server_uri=server_uri,
            hash=new_hash,
        )
        return server, False, None

    if existing.trust_level == "blocked":
        # Still update last_seen_at so the dashboard sees the attempt
        # but signal the block to the caller via an exception.
        existing.last_seen_at = now
        await db.flush()
        raise MCPServerBlockedError(
            f"MCP server {server_uri} is blocked by org policy"
        )

    if existing.manifest_hash == new_hash:
        existing.last_seen_at = now
        if server_name and existing.server_name != server_name:
            existing.server_name = server_name
        await db.flush()
        return existing, False, None

    # Hash changed → drift
    previous_hash = existing.manifest_hash
    previous_trust_level = existing.trust_level

    history: list[dict[str, Any]] = list(existing.hash_history or [])  # type: ignore[arg-type]
    history.append(
        {
            "hash": new_hash,
            "changed_at": now.isoformat(),
            "previous_hash": previous_hash,
        }
    )
    existing.hash_history = history[-_HASH_HISTORY_MAX:]  # type: ignore[assignment]
    existing.manifest = manifest
    existing.manifest_hash = new_hash
    existing.tool_count = count
    existing.last_seen_at = now
    if server_name:
        existing.server_name = server_name

    # Auto-downgrade if previously trusted — admin must re-approve.
    downgraded_from: str | None = None
    if previous_trust_level == "trusted":
        existing.trust_level = "observed"
        downgraded_from = "trusted"
        log.warning(
            "mcp.trust_downgraded_on_drift",
            server_id=str(existing.id),
            previous_hash=previous_hash,
            new_hash=new_hash,
        )
    else:
        log.info(
            "mcp.manifest_drift",
            server_id=str(existing.id),
            previous_hash=previous_hash,
            new_hash=new_hash,
        )

    await db.flush()
    return existing, True, downgraded_from


async def list_servers(
    db: AsyncSession, org_id: uuid.UUID
) -> list[MCPServer]:
    result = await db.execute(
        select(MCPServer)
        .where(MCPServer.org_id == org_id)
        .order_by(MCPServer.last_seen_at.desc())
    )
    return list(result.scalars().all())


async def get_server(
    db: AsyncSession, org_id: uuid.UUID, server_id: uuid.UUID
) -> MCPServer:
    result = await db.execute(
        select(MCPServer).where(
            MCPServer.id == server_id, MCPServer.org_id == org_id
        )
    )
    server = result.scalar_one_or_none()
    if server is None:
        raise NotFoundError("MCPServer", str(server_id))
    return server


async def set_trust_level(
    db: AsyncSession,
    org_id: uuid.UUID,
    server_id: uuid.UUID,
    trust_level: str,
) -> MCPServer:
    if trust_level not in _VALID_TRUST_LEVELS:
        raise ValueError(f"invalid trust_level: {trust_level}")
    server = await get_server(db, org_id, server_id)
    server.trust_level = trust_level
    await db.flush()
    log.info(
        "mcp.trust_level_changed",
        server_id=str(server_id),
        trust_level=trust_level,
    )
    return server
