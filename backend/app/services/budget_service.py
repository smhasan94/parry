"""Budget enforcement service.

Tracks per-agent spend in Redis counters (hourly / daily / monthly)
and checks incoming events against database-defined caps. All Redis
operations fail open — a Redis outage must never block agent calls.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentBudget, Org
from app.services.alert_service import BudgetAlertContext, dispatch_budget_alert

log = structlog.get_logger()

# Period → Redis key suffix and TTL (seconds).
_PERIOD_META: dict[str, tuple[str, int]] = {
    "hour": ("h", 3_700),
    "day": ("d", 90_000),
    "month": ("m", 32 * 86_400),
}


def _get_redis() -> Any:
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


def _alert_dedup_key(budget_id: uuid.UUID, period_key: str, pct: int) -> str:
    """Redis key used to prevent duplicate budget threshold alerts."""
    return f"budget_alert_fired:{budget_id}:{period_key}:{pct}"


def _current_period_key(period: str) -> str:
    """Return a short string representing the current period bucket.

    Used as part of the dedup key so that alerts reset when a new period begins.
    The key matches the TTL bucket set on the spend counter itself.
    """
    import time

    now = int(time.time())
    if period == "hour":
        return str(now // 3600)
    if period == "day":
        return str(now // 86400)
    # month — approximate via 30-day buckets
    return str(now // (30 * 86400))


def _check_and_mark_threshold(r: Any, budget_id: uuid.UUID, period: str, pct: int) -> bool:
    """Return True if this threshold should fire (not previously fired this period).

    Sets the dedup key in Redis with a TTL matching the budget period so that
    the flag resets automatically at the start of the next period.
    """
    period_key = _current_period_key(period)
    key = _alert_dedup_key(budget_id, period_key, pct)
    _, ttl = _PERIOD_META[period]
    try:
        # SET key 1 NX EX ttl — atomically set only if not exists
        set_result = r.set(key, "1", nx=True, ex=ttl)
        return bool(set_result)
    except Exception:
        log.debug("budget.dedup_check_failed", exc_info=True)
        return False


async def _load_org(db: AsyncSession, org_id: uuid.UUID) -> Org | None:
    result = await db.execute(select(Org).where(Org.id == org_id))
    return result.scalar_one_or_none()


async def _fire_threshold_alerts(
    db: AsyncSession,
    budget: AgentBudget,
    agent: Agent,
    current_spend: float,
) -> None:
    """Check configured percentage thresholds and fire alerts for newly crossed ones.

    Each threshold fires at most once per budget period, enforced via Redis NX keys.
    Fails silently so that alert delivery never blocks the main request path.
    """
    alert_pcts: list[int] = budget.alert_at_pcts or []
    if not alert_pcts:
        return

    cap = float(budget.cap_usd)
    if cap <= 0:
        return

    pct_used = (current_spend / cap) * 100.0
    r = _get_redis()
    if r is None:
        return

    crossed: list[int] = [p for p in alert_pcts if pct_used >= p]
    if not crossed:
        return

    # Load org once only if there are thresholds to fire
    org = await _load_org(db, budget.org_id)
    if org is None:
        return

    for pct in crossed:
        if not _check_and_mark_threshold(r, budget.id, budget.period, pct):
            # Already fired for this period
            continue

        ctx = BudgetAlertContext(
            budget_id=budget.id,
            agent_id=agent.id,
            agent_name=agent.name,
            org_id=budget.org_id,
            period=budget.period,
            cap_usd=cap,
            current_spend=current_spend,
            threshold_pct=pct,
        )
        try:
            await dispatch_budget_alert(org, ctx)
        except Exception:
            log.warning(
                "budget.threshold_alert_failed",
                budget_id=str(budget.id),
                pct=pct,
                exc_info=True,
            )


async def _load_budget(db: AsyncSession, agent_id: uuid.UUID) -> AgentBudget | None:
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

    Also fires threshold alerts for any configured ``alert_at_pcts``
    that have been newly crossed this period.

    Fails open: any error → (True, None).
    """
    try:
        budget = await _load_budget(db, agent_id)
        if budget is None:
            return True, None

        period = budget.period
        current_spend = get_spend(agent_id, period)
        projected = current_spend + event_cost
        cap = float(budget.cap_usd)
        threshold = cap * 0.95

        # Load the agent so we have a name for alert messages.
        agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent_result.scalar_one_or_none()

        if agent is not None:
            # Fire threshold alerts based on projected spend (includes this event).
            await _fire_threshold_alerts(db, budget, agent, projected)

        if projected >= threshold:
            reason = (
                f"Budget exceeded: ${current_spend:.4f} spent of "
                f"${cap:.2f} {period} cap (95% threshold)"
            )
            log.info(
                "budget.blocked",
                agent_id=str(agent_id),
                period=period,
                spend=current_spend,
                cap=cap,
            )
            return False, reason

        return True, None
    except Exception:
        log.debug("budget.check_spend_failed", exc_info=True)
        return True, None
