"""MCP (Model Context Protocol) API.

Two shapes of auth:

- `POST /mcp/connections` and `POST /mcp/events` are SDK-runtime
  paths authenticated by ``X-Parry-Secret`` (the same pattern as the
  event ingest path). They must be fast and must not require a full
  JWT.
- Every GET + PATCH is dashboard-facing, authenticated by the
  standard Clerk JWT via ``require_role``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_org_from_sdk_key
from app.core.rbac import Role, require_role
from app.core.url_guard import InvalidServerURIError, validate_mcp_server_uri
from app.db.models import MCPServer, Org
from app.db.session import get_db
from app.detection.detectors.mcp_manifest import scan_manifest
from app.schemas.base import ParrySchema
from app.services import audit_service, mcp_service, plan_service

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


# A manifest this large is a payload, not a tool list. The 2MB body cap
# in RequestSizeLimitMiddleware bounds the bytes; this bounds the shape,
# since the manifest detector walks every tool and every schema property.
MAX_MANIFEST_TOOLS = 1_000


class MCPConnectionRequest(ParrySchema):
    agent_id: str
    server_uri: str
    transport: Literal["stdio", "http", "sse"] | None = None
    server_name: str | None = None
    manifest: dict[str, Any]

    @model_validator(mode="after")
    def _canonicalise_uri(self) -> MCPConnectionRequest:
        """Normalise the URI and derive the transport it implies.

        Runs at the boundary rather than in the service because a
        credential-bearing URI has to be refused before anything
        durable happens to it.
        """
        try:
            parsed = validate_mcp_server_uri(self.server_uri, self.transport)
        except InvalidServerURIError as exc:
            raise ValueError(str(exc)) from exc

        tools = self.manifest.get("tools")
        if isinstance(tools, list) and len(tools) > MAX_MANIFEST_TOOLS:
            raise ValueError(f"manifest declares more than {MAX_MANIFEST_TOOLS} tools")

        self.server_uri = parsed.uri
        self.transport = parsed.transport
        return self


class MCPDetection(ParrySchema):
    detector: str
    severity: str
    reason: str
    confidence: float
    details: dict[str, Any] | None = None


class MCPConnectionResponse(ParrySchema):
    server_id: str
    trust_level: str
    manifest_changed: bool
    previous_trust_level: str | None = None
    previous_hash: str | None = None
    new_hash: str
    detections: list[MCPDetection]


class MCPServerSummary(ParrySchema):
    id: str
    server_uri: str
    transport: str
    server_name: str | None
    trust_level: str
    reputation: int
    tool_count: int
    manifest_hash: str
    first_seen_at: datetime
    last_seen_at: datetime


class MCPServerDetail(MCPServerSummary):
    manifest: dict[str, Any]
    hash_history: list[dict[str, Any]]


class MCPServerPatch(ParrySchema):
    trust_level: Literal["observed", "trusted", "suspicious", "blocked"] | None = None
    server_name: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _summary(server: MCPServer) -> dict[str, Any]:
    return {
        "id": str(server.id),
        "server_uri": server.server_uri,
        "transport": server.transport,
        "server_name": server.server_name,
        "trust_level": server.trust_level,
        "reputation": server.reputation,
        "tool_count": server.tool_count,
        "manifest_hash": server.manifest_hash,
        "first_seen_at": server.first_seen_at,
        "last_seen_at": server.last_seen_at,
    }


# ── SDK-runtime routes ──────────────────────────────────────────────


@router.post("/connections", response_model=MCPConnectionResponse)
async def register_connection(
    body: MCPConnectionRequest,
    org: Org = Depends(get_org_from_sdk_key),
    db: AsyncSession = Depends(get_db),
) -> MCPConnectionResponse:
    """Called by SentinelMCPClient on every connect.

    Upserts the server row, computes drift, runs the manifest
    detector, and returns the combined verdict. The SDK decides
    whether to raise ``MCPBlockedError`` based on the detections
    list (CRITICAL) or the 403 path (blocked trust level).
    """
    plan_service.require_feature(org, "mcp_security")

    try:
        server, changed, downgraded_from = await mcp_service.upsert_server(
            db,
            org.id,
            server_uri=body.server_uri,
            server_name=body.server_name,
            manifest=body.manifest,
            transport=body.transport or "stdio",
        )
    except mcp_service.MCPServerBlockedError as e:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
            headers={"X-Parry-Code": "MCP_SERVER_BLOCKED"},
        ) from e

    # Run the manifest detector synchronously. It's pure/fast — no
    # reason to round-trip through the async pipeline for an inline
    # auth check.
    findings = scan_manifest(body.manifest)
    detections: list[MCPDetection] = []
    if findings:
        has_smuggling = any(
            f["category"] == "unicode_smuggling" for f in findings
        )
        severity = "critical" if has_smuggling else "high"
        detections.append(
            MCPDetection(
                detector="mcp_manifest",
                severity=severity,
                confidence=0.95,
                reason=(
                    f"Tool '{findings[0]['tool_name']}' "
                    f"{findings[0]['field']} triggers "
                    f"{findings[0]['category']}"
                ),
                details={"findings": findings, "count": len(findings)},
            )
        )
        # Auto-mark the server suspicious on a fresh critical hit.
        if severity == "critical" and server.trust_level == "observed":
            server.trust_level = "suspicious"

    previous_hash: str | None = None
    if changed and server.hash_history:
        history_tail = server.hash_history[-1]
        if isinstance(history_tail, dict):
            previous_hash = history_tail.get("previous_hash")

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="mcp.connection_registered",
        actor_type="api_key",
        actor_id=None,
        actor_label=f"agent:{body.agent_id}",
        resource_type="mcp_server",
        resource_id=str(server.id),
        details={
            "server_uri": body.server_uri,
            "manifest_changed": changed,
            "downgraded_from": downgraded_from,
            "detection_count": len(detections),
        },
    )
    await db.commit()

    return MCPConnectionResponse(
        server_id=str(server.id),
        trust_level=server.trust_level,
        manifest_changed=changed,
        previous_trust_level=downgraded_from,
        previous_hash=previous_hash,
        new_hash=server.manifest_hash,
        detections=detections,
    )


# ── Dashboard routes ────────────────────────────────────────────────


@router.get("/servers", response_model=list[MCPServerSummary])
async def list_servers(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[MCPServerSummary]:
    org, _ = org_actor
    servers = await mcp_service.list_servers(db, org.id)
    return [MCPServerSummary(**_summary(s)) for s in servers]


@router.get("/servers/{server_id}", response_model=MCPServerDetail)
async def get_server(
    server_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> MCPServerDetail:
    org, _ = org_actor
    server = await mcp_service.get_server(db, org.id, server_id)
    return MCPServerDetail(
        **_summary(server),
        manifest=server.manifest,
        hash_history=server.hash_history or [],
    )


@router.patch("/servers/{server_id}", response_model=MCPServerSummary)
async def patch_server(
    server_id: uuid.UUID,
    body: MCPServerPatch,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> MCPServerSummary:
    org, actor = org_actor
    server = await mcp_service.get_server(db, org.id, server_id)

    changes: dict[str, Any] = {}
    if body.trust_level is not None and body.trust_level != server.trust_level:
        changes["trust_level"] = {
            "before": server.trust_level,
            "after": body.trust_level,
        }
        server.trust_level = body.trust_level
    if body.server_name is not None and body.server_name != server.server_name:
        changes["server_name"] = {
            "before": server.server_name,
            "after": body.server_name,
        }
        server.server_name = body.server_name

    await db.flush()

    if changes:
        await audit_service.log_action(
            db,
            org_id=org.id,
            action="mcp.server_updated",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_label=actor.label,
            resource_type="mcp_server",
            resource_id=str(server.id),
            details={"changes": changes},
        )
    await db.commit()
    return MCPServerSummary(**_summary(server))
