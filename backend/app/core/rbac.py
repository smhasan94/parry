"""Role-based access control dependencies.

Three tiers enforced per route via `Depends(require_role(Role.X))`:

- VIEWER — read-only access, no mutations anywhere
- ADMIN  — full CRUD except billing and org deletion
- OWNER  — everything including billing

API key auth (SDK) is always treated as ADMIN: agents need write
access to ingest events but should never be able to touch billing.

Role comes from the Clerk JWT's `org_role` claim via
dependencies._resolve_from_clerk_jwt. Missing/unknown claim defaults
to VIEWER — we never fail open on permissions.
"""

from __future__ import annotations

import enum
from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.core.dependencies import Actor, get_current_actor
from app.db.models import Org


class Role(enum.IntEnum):
    """Integer enum so comparisons work: Role.OWNER >= Role.ADMIN."""

    VIEWER = 0
    ADMIN = 1
    OWNER = 2


# Clerk role strings → Role enum. Anything not in this map falls back
# to VIEWER (the least privileged tier).
ROLE_MAP: dict[str, Role] = {
    "org:viewer": Role.VIEWER,
    "org:member": Role.VIEWER,  # Clerk default member role
    "org:admin": Role.ADMIN,
    "org:owner": Role.OWNER,
}


def actor_role(actor: Actor) -> Role:
    """Resolve the effective Role for an Actor.

    Order of precedence:

    1. API keys (actor_type == 'api_key') → VIEWER.

       An SDK API key is a runtime credential — it authenticates
       /proxy/check, /events/ingest, and /proxy/scan-response via
       the X-Parry-Secret header, none of which pass through this
       role resolver at all. Anyone using the same key via
       Authorization: Bearer on a dashboard route gets read-only
       access, not admin. This contains the blast radius of a
       leaked SDK key: the attacker can read dashboard state but
       can't export the audit log, rotate keys, mutate policies,
       generate SSO admin portal links, or delete agents.

       Customers who need curl-friendly management access should
       use a Clerk JWT (the documented path) — a separate
       management-key scope can be added later if real demand
       shows up.

    2. System actors (background jobs) → OWNER.
    3. User actors → lookup from clerk_role, default VIEWER.
    """
    if actor.actor_type == "api_key":
        return Role.VIEWER
    if actor.actor_type == "system":
        return Role.OWNER

    role_str = getattr(actor, "clerk_role", None) or ""
    return ROLE_MAP.get(role_str, Role.VIEWER)


def require_role(min_role: Role) -> Callable:
    """Dependency factory for FastAPI routes.

    Usage:
        @router.post("/agents", dependencies=[Depends(require_role(Role.ADMIN))])

    Or injected so the handler receives the (org, actor) tuple:
        async def create_agent(
            org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
        ): ...
    """

    async def _check(
        actor_tuple: tuple[Org, Actor] = Depends(get_current_actor),
    ) -> tuple[Org, Actor]:
        org, actor = actor_tuple
        if actor_role(actor) < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role.name.lower()} role",
                headers={"X-Required-Role": min_role.name.lower()},
            )
        return org, actor

    return _check
