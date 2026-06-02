"""Unit tests for mcp_service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.db.models import MCPServer
from app.services import mcp_service
from app.services.mcp_service import MCPServerBlockedError

ORG_ID = uuid.uuid4()

_MANIFEST = {"tools": [{"name": "search"}, {"name": "browse"}]}
_HASH_A = "aaaa" * 16
_HASH_B = "bbbb" * 16


def _make_server(
    org_id: uuid.UUID | None = None,
    server_uri: str = "https://mcp.example.com",
    trust_level: str = "observed",
    manifest_hash: str = _HASH_A,
) -> MCPServer:
    now = datetime.now(timezone.utc)
    return MCPServer(
        id=uuid.uuid4(),
        org_id=org_id or ORG_ID,
        server_uri=server_uri,
        server_name="Example MCP",
        manifest=_MANIFEST,
        manifest_hash=manifest_hash,
        tool_count=2,
        trust_level=trust_level,
        reputation=50,
        hash_history=[{"hash": manifest_hash, "seen_at": now.isoformat()}],
        first_seen_at=now,
        last_seen_at=now,
    )


def _scalar_one_or_none(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _scalars_returning(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


# ── upsert_server — new registration ─────────────────────────────


@pytest.mark.asyncio
async def test_upsert_server_registers_new_server_as_observed() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)  # no existing server

    with patch.object(mcp_service, "manifest_hash", return_value=_HASH_A), \
         patch.object(mcp_service, "tool_count", return_value=2):
        server, changed, downgraded = await mcp_service.upsert_server(
            db, ORG_ID,
            server_uri="https://mcp.example.com",
            server_name="Example MCP",
            manifest=_MANIFEST,
        )

    assert server.trust_level == "observed"
    assert server.manifest_hash == _HASH_A
    assert changed is False
    assert downgraded is None
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


# ── upsert_server — same hash (heartbeat) ─────────────────────────


@pytest.mark.asyncio
async def test_upsert_server_same_hash_updates_last_seen_only() -> None:
    existing = _make_server(trust_level="trusted", manifest_hash=_HASH_A)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(existing)

    with patch.object(mcp_service, "manifest_hash", return_value=_HASH_A), \
         patch.object(mcp_service, "tool_count", return_value=2):
        server, changed, downgraded = await mcp_service.upsert_server(
            db, ORG_ID,
            server_uri=existing.server_uri,
            server_name=existing.server_name,
            manifest=_MANIFEST,
        )

    assert changed is False
    assert downgraded is None
    assert server.trust_level == "trusted"
    db.flush.assert_awaited_once()


# ── upsert_server — hash drift on non-trusted ─────────────────────


@pytest.mark.asyncio
async def test_upsert_server_hash_drift_on_observed_does_not_downgrade() -> None:
    existing = _make_server(trust_level="observed", manifest_hash=_HASH_A)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(existing)

    with patch.object(mcp_service, "manifest_hash", return_value=_HASH_B), \
         patch.object(mcp_service, "tool_count", return_value=3):
        server, changed, downgraded = await mcp_service.upsert_server(
            db, ORG_ID,
            server_uri=existing.server_uri,
            server_name=existing.server_name,
            manifest=_MANIFEST,
        )

    assert changed is True
    assert downgraded is None
    assert server.trust_level == "observed"
    assert server.manifest_hash == _HASH_B


# ── upsert_server — hash drift on trusted → downgrade ─────────────


@pytest.mark.asyncio
async def test_upsert_server_hash_drift_on_trusted_downgrades_to_observed() -> None:
    existing = _make_server(trust_level="trusted", manifest_hash=_HASH_A)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(existing)

    with patch.object(mcp_service, "manifest_hash", return_value=_HASH_B), \
         patch.object(mcp_service, "tool_count", return_value=3):
        server, changed, downgraded = await mcp_service.upsert_server(
            db, ORG_ID,
            server_uri=existing.server_uri,
            server_name=existing.server_name,
            manifest=_MANIFEST,
        )

    assert changed is True
    assert downgraded == "trusted"
    assert server.trust_level == "observed"


# ── upsert_server — blocked server ────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_server_blocked_raises_mcp_server_blocked_error() -> None:
    existing = _make_server(trust_level="blocked")
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(existing)

    with patch.object(mcp_service, "manifest_hash", return_value=_HASH_A), \
         patch.object(mcp_service, "tool_count", return_value=2), \
         pytest.raises(MCPServerBlockedError):
        await mcp_service.upsert_server(
            db, ORG_ID,
            server_uri=existing.server_uri,
            server_name=existing.server_name,
            manifest=_MANIFEST,
        )

    db.flush.assert_awaited_once()


# ── list_servers ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_servers_returns_all_for_org() -> None:
    servers = [_make_server(), _make_server(server_uri="https://other.com")]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(servers)

    result = await mcp_service.list_servers(db, ORG_ID)

    assert result == servers


@pytest.mark.asyncio
async def test_list_servers_returns_empty_list_when_none() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    result = await mcp_service.list_servers(db, uuid.uuid4())

    assert result == []


# ── get_server ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_server_returns_server() -> None:
    server = _make_server()
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(server)

    result = await mcp_service.get_server(db, ORG_ID, server.id)

    assert result is server


@pytest.mark.asyncio
async def test_get_server_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await mcp_service.get_server(db, ORG_ID, uuid.uuid4())


# ── set_trust_level ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_trust_level_updates_to_trusted() -> None:
    server = _make_server(trust_level="observed")
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(server)

    result = await mcp_service.set_trust_level(db, ORG_ID, server.id, "trusted")

    assert result.trust_level == "trusted"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_trust_level_updates_to_blocked() -> None:
    server = _make_server(trust_level="observed")
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(server)

    result = await mcp_service.set_trust_level(db, ORG_ID, server.id, "blocked")

    assert result.trust_level == "blocked"


@pytest.mark.asyncio
async def test_set_trust_level_raises_value_error_for_invalid_level() -> None:
    server = _make_server()
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(server)

    with pytest.raises(ValueError, match="invalid trust_level"):
        await mcp_service.set_trust_level(db, ORG_ID, server.id, "unknown")
