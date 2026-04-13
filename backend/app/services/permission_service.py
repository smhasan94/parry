"""Agent permission boundary service.

Evaluates whether an agent is allowed to call a specific tool based on
per-agent or org-wide permission records. Enforced at the proxy layer
independently of blocking_enabled.

Resolution order:
1. Agent-specific permission (agent_id = target agent)
2. Org-wide default (agent_id = NULL)
3. No record → allow all (backwards compatible)
"""

import uuid
from dataclasses import dataclass
from typing import Literal, cast

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentPermission

log = structlog.get_logger()


@dataclass(frozen=True)
class PermissionResult:
    """Result of a permission check."""

    allowed: bool
    mode: Literal["enforcing", "dry_run", "disabled"]
    reason: str
    tool_name: str
    agent_id: str
    source: Literal["agent", "org_default", "no_record"]


async def check_permission(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    tool_name: str,
) -> PermissionResult:
    """Check if an agent is allowed to call a tool.

    Returns a PermissionResult with allowed=True/False and the reason.
    When no permission record exists, the agent is allowed (backwards
    compatible — existing customers aren't broken).
    """
    # 1. Try agent-specific permission
    result = await db.execute(
        select(AgentPermission).where(
            AgentPermission.org_id == org_id,
            AgentPermission.agent_id == agent_id,
        )
    )
    perm = result.scalar_one_or_none()
    if perm:
        return _evaluate(perm, tool_name, str(agent_id), source="agent")

    # 2. Try group-level permission (if agent belongs to a group)
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    if agent and agent.group_id:
        group_perm_result = await db.execute(
            select(AgentPermission).where(
                AgentPermission.org_id == org_id,
                AgentPermission.agent_id == agent.group_id,
            )
        )
        group_perm = group_perm_result.scalar_one_or_none()
        if group_perm:
            return _evaluate(group_perm, tool_name, str(agent_id), source="org_default")

    # 3. Try org-wide default (agent_id IS NULL)
    result = await db.execute(
        select(AgentPermission).where(
            AgentPermission.org_id == org_id,
            AgentPermission.agent_id.is_(None),
        )
    )
    perm = result.scalar_one_or_none()
    if perm:
        return _evaluate(perm, tool_name, str(agent_id), source="org_default")

    # 4. No record → allow all
    return PermissionResult(
        allowed=True,
        mode="disabled",
        reason="No permission record — allow all",
        tool_name=tool_name,
        agent_id=str(agent_id),
        source="no_record",
    )


def evaluate_permission(
    perm: AgentPermission,
    tool_name: str,
    agent_id: str,
) -> PermissionResult:
    """Pure evaluation function for testing without DB.

    Determines whether a tool call is allowed based on a permission
    record's mode, default_action, and tool lists.
    """
    return _evaluate(perm, tool_name, agent_id, source="agent")


def _evaluate(
    perm: AgentPermission,
    tool_name: str,
    agent_id: str,
    source: Literal["agent", "org_default"],
) -> PermissionResult:
    """Core evaluation logic."""
    mode = cast(Literal["enforcing", "dry_run", "disabled"], perm.mode)
    if mode == "disabled":
        return PermissionResult(
            allowed=True,
            mode="disabled",
            reason="Permissions disabled",
            tool_name=tool_name,
            agent_id=agent_id,
            source=source,
        )

    allowed_tools: list[str] = perm.allowed_tools or []
    blocked_tools: list[str] = perm.blocked_tools or []

    # Normalize tool name for comparison
    tool_lower = tool_name.lower()
    allowed_lower = [t.lower() for t in allowed_tools]
    blocked_lower = [t.lower() for t in blocked_tools]

    # Explicit blocklist always wins
    if tool_lower in blocked_lower:
        return PermissionResult(
            allowed=False,
            mode=mode,
            reason=f"Tool '{tool_name}' is explicitly blocked",
            tool_name=tool_name,
            agent_id=agent_id,
            source=source,
        )

    # Explicit allowlist always wins
    if tool_lower in allowed_lower:
        return PermissionResult(
            allowed=True,
            mode=mode,
            reason=f"Tool '{tool_name}' is explicitly allowed",
            tool_name=tool_name,
            agent_id=agent_id,
            source=source,
        )

    # Default action for unlisted tools
    if perm.default_action == "deny":
        return PermissionResult(
            allowed=False,
            mode=mode,
            reason=f"Tool '{tool_name}' not in allowlist (deny-by-default)",
            tool_name=tool_name,
            agent_id=agent_id,
            source=source,
        )

    # default_action == "allow"
    return PermissionResult(
        allowed=True,
        mode=mode,
        reason=f"Tool '{tool_name}' permitted (allow-by-default)",
        tool_name=tool_name,
        agent_id=agent_id,
        source=source,
    )


# ── CRUD helpers ────────────────────────────────────────────────


async def get_permission(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> AgentPermission | None:
    """Get permission record for a specific agent or org default."""
    if agent_id is not None:
        result = await db.execute(
            select(AgentPermission).where(
                AgentPermission.org_id == org_id,
                AgentPermission.agent_id == agent_id,
            )
        )
    else:
        result = await db.execute(
            select(AgentPermission).where(
                AgentPermission.org_id == org_id,
                AgentPermission.agent_id.is_(None),
            )
        )
    return result.scalar_one_or_none()


async def upsert_permission(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    *,
    mode: str = "disabled",
    default_action: str = "allow",
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
) -> AgentPermission:
    """Create or update a permission record."""
    perm = await get_permission(db, org_id, agent_id)
    if perm is None:
        perm = AgentPermission(
            org_id=org_id,
            agent_id=agent_id,
            mode=mode,
            default_action=default_action,
            allowed_tools=allowed_tools or [],
            blocked_tools=blocked_tools or [],
        )
        db.add(perm)
    else:
        perm.mode = mode
        perm.default_action = default_action
        perm.allowed_tools = allowed_tools or []
        perm.blocked_tools = blocked_tools or []

    await db.flush()
    await db.refresh(perm)
    log.info(
        "permission.upserted",
        org_id=str(org_id),
        agent_id=str(agent_id) if agent_id else "org_default",
        mode=mode,
        default_action=default_action,
    )
    return perm


async def delete_permission(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> bool:
    """Delete a permission record. Returns True if found and deleted."""
    perm = await get_permission(db, org_id, agent_id)
    if perm is None:
        return False
    await db.delete(perm)
    await db.flush()
    log.info(
        "permission.deleted",
        org_id=str(org_id),
        agent_id=str(agent_id) if agent_id else "org_default",
    )
    return True
