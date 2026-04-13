"""Budget enforcement service.

Tracks per-agent spend in Redis counters (hourly / daily / monthly)
and checks incoming events against database-defined caps. All Redis
operations fail open — a Redis outage must never block agent calls.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentBudget

log = structlog.get_logger()

# Period → Redis key suffix and TTL (seconds).
_PERIOD_META: dict[str, tuple[str, int]] = {
    "hour": ("h", 3_700),
    "day": ("d", 90_000),
    "month": ("m", 32 * 86_400),
}


def _get_redis():
    """Sync Redis client from shared pool."""
    try:
        from app.core.redis_pool import sync_redis

        return sync_redis()
    except Exception:
        log.debug("budget.redis_unavailable", exc_info=True)
        return None


def _budget_key(agent_id: uuid.UUID, suffix: str) -> str:
    return f"budget:{agent_id}:{suffix}"


def record_spend(agent_id: uuid.UUID, cost_usd: float) -> None:
    """Increment spend counters for all three periods. Fire-and-forget."""
    if cost_usd <= 0:
        return
    r = _get_redis()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        for _period, (suffix, ttl) in _PERIOD_META.items():
            key = _budget_key(agent_id, suffix)
            pipe.incrbyfloat(key, cost_usd)
            pipe.expire(key, ttl)
        pipe.execute()
    except Exception:
        log.debug("budget.record_spend_failed", exc_info=True)


def get_spend(agent_id: uuid.UUID, period: str) -> float:
    """Return current spend for a period. Returns 0.0 on Redis errors."""
    meta = _PERIOD_META.get(period)
    if meta is None:
        return 0.0
    suffix, _ = meta
    r = _get_redis()
    if r is None:
        return 0.0
    try:
        val = r.get(_budget_key(agent_id, suffix))
        return float(val) if val is not None else 0.0
    except Exception:
        log.debug("budget.get_spend_failed", exc_info=True)
        return 0.0


async def _load_budget(
    db: AsyncSession, agent_id: uuid.UUID
) -> AgentBudget | None:
    """Load the most specific enabled budget for an agent.

    Prefers an agent-specific budget over an org-wide default
    (agent_id IS NULL). Returns None when no budget is configured.
    """
    # First try agent-specific
    result = await db.execute(
        select(AgentBudget).where(
            AgentBudget.agent_id == agent_id,
            AgentBudget.enabled.is_(True),
        )
    )
    budget = result.scalar_one_or_none()
    if budget is not None:
        return budget

    # Fall back to org-wide default: find the agent's org, then look
    # for a budget with agent_id=NULL for that org.
    agent_result = await db.execute(select(Agent.org_id).where(Agent.id == agent_id))
    org_id = agent_result.scalar_one_or_none()
    if org_id is None:
        return None

    result = await db.execute(
        select(AgentBudget).where(
            AgentBudget.org_id == org_id,
            AgentBudget.agent_id.is_(None),
            AgentBudget.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def check_spend(
    db: AsyncSession, agent_id: uuid.UUID, event_cost: float = 0.0
) -> tuple[bool, str | None]:
    """Check whether the agent is within budget.

    Returns (allowed, reason). ``allowed=True`` means the call may
    proceed. Blocks at 95% of cap to leave headroom for the last
    in-flight call.

    Fails open: any error → (True, None).
    """
    try:
        budget = await _load_budget(db, agent_id)
        if budget is None:
            return True, None

        period = budget.period
        current_spend = get_spend(agent_id, period)
        projected = current_spend + event_cost
        threshold = float(budget.cap_usd) * 0.95

        if projected >= threshold:
            reason = (
                f"Budget exceeded: ${current_spend:.4f} spent of "
                f"${float(budget.cap_usd):.2f} {period} cap (95% threshold)"
            )
            log.info(
                "budget.blocked",
                agent_id=str(agent_id),
                period=period,
                spend=current_spend,
                cap=float(budget.cap_usd),
            )
            return False, reason

        return True, None
    except Exception:
        log.debug("budget.check_spend_failed", exc_info=True)
        return True, None
