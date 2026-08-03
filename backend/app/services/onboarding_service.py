"""What a brand-new org starts with.

Org creation used to insert a bare row, so a customer's first five
minutes were an empty dashboard: nothing to react to, and no obvious
first move.

Everything provisioned here is inert on arrival. A new customer's agents
must behave exactly as they did before they signed up — the defaults are
there to be found and edited, not to take effect unreviewed. Two
consequences worth stating, because both look like omissions:

* The starter policy is inactive and carries no rules. Agent tool names
  are application-specific, so any blocklist we shipped would be a guess
  that produces false detections on day one.
* ``detector_config`` is deliberately left unset. Writing today's
  defaults into the row would pin the org to them, and later tuning
  improvements would never reach it. ``None`` means "use the platform
  defaults, whatever they currently are".

Idempotent, so it is safe to call on every org-created webhook delivery
and to backfill over orgs that predate it.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentPermission, Org, Policy
from app.services import audit_service

log = structlog.get_logger()

_STARTER_POLICY_NAME = "Default policy"
_STARTER_POLICY_DESCRIPTION = (
    "Starter policy — inactive until you enable it. Add the tools your "
    "agents are allowed or forbidden to call, then activate. While "
    "inactive it has no effect on detection."
)


async def _has_org_default_permission(db: AsyncSession, org_id: Any) -> bool:
    result = await db.execute(
        select(AgentPermission.id).where(
            AgentPermission.org_id == org_id,
            AgentPermission.agent_id.is_(None),
        )
    )
    return result.first() is not None


async def _has_any_policy(db: AsyncSession, org_id: Any) -> bool:
    result = await db.execute(select(Policy.id).where(Policy.org_id == org_id))
    return result.first() is not None


async def provision_new_org(db: AsyncSession, org: Org) -> dict[str, Any]:
    """Give a new org its starting configuration.

    Returns ``{"provisioned": bool, "created": [...]}``. ``provisioned``
    is False when there was nothing to do, so a repeated webhook
    delivery is a no-op rather than a duplicate.
    """
    created: list[str] = []

    if not await _has_org_default_permission(db, org.id):
        db.add(
            AgentPermission(
                org_id=org.id,
                agent_id=None,  # org-wide default
                # allow + empty lists denies nothing today. dry_run means
                # the first tool they add to the blocklist is observed
                # before it is enforced, rather than silently breaking a
                # live agent.
                mode="dry_run",
                default_action="allow",
                allowed_tools=[],
                blocked_tools=[],
            )
        )
        created.append("permission_boundary")

    if not await _has_any_policy(db, org.id):
        db.add(
            Policy(
                org_id=org.id,
                name=_STARTER_POLICY_NAME,
                description=_STARTER_POLICY_DESCRIPTION,
                is_active=False,
            )
        )
        created.append("starter_policy")

    # detector_config is intentionally not written — see module docstring.

    if not created:
        return {"provisioned": False, "created": []}

    await db.flush()
    await audit_service.log_action(
        db,
        org.id,
        "org.provisioned",
        actor_type="system",
        resource_type="org",
        resource_id=str(org.id),
        details={"created": created},
    )

    log.info("org.provisioned", org_id=str(org.id), created=created)
    return {"provisioned": True, "created": created}
