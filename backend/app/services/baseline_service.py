"""Auto-generate behavioral baselines for agents from their event history."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent

log = structlog.get_logger()

MIN_EVENTS = 20
HIGH_QUALITY_EVENTS = 200
MEDIUM_QUALITY_EVENTS = 50


def classify_quality(event_count: int) -> str:
    """Classify how trustworthy a baseline is based on its sample size.

    - low:    < MEDIUM_QUALITY_EVENTS — std dev is wobbly, alerts get noisy
    - medium: < HIGH_QUALITY_EVENTS   — usable for alerts but flag in UI
    - high:   >= HIGH_QUALITY_EVENTS  — fully trusted
    """
    if event_count >= HIGH_QUALITY_EVENTS:
        return "high"
    if event_count >= MEDIUM_QUALITY_EVENTS:
        return "medium"
    return "low"


async def compute_baseline(
    db: AsyncSession,
    agent_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Compute a behavioral baseline from the agent's event history.

    Returns None if the agent has fewer than MIN_EVENTS events.
    """
    # Count events
    count_result = await db.execute(
        select(func.count()).select_from(AgentEvent).where(AgentEvent.agent_id == agent_id)
    )
    event_count = count_result.scalar_one()

    if event_count < MIN_EVENTS:
        return None

    # Aggregate stats
    result = await db.execute(
        select(
            func.coalesce(func.avg(AgentEvent.token_count), 0.0).label("avg_token_count"),
            func.coalesce(func.stddev_pop(AgentEvent.token_count), 0.0).label("std_token_count"),
            func.coalesce(func.avg(AgentEvent.latency_ms), 0.0).label("avg_latency_ms"),
            func.coalesce(func.stddev_pop(AgentEvent.latency_ms), 0.0).label("std_latency_ms"),
        ).where(AgentEvent.agent_id == agent_id)
    )
    row = result.one()

    # Get distinct models
    models_result = await db.execute(
        select(func.distinct(AgentEvent.model)).where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.model.is_not(None),
        )
    )
    known_models = [m for (m,) in models_result.all()]

    # Average tool call count — fetch tool_calls arrays and count in Python
    # (jsonb_array_length fails on non-array JSONB values)
    tool_result = await db.execute(
        select(AgentEvent.tool_calls).where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.tool_calls.is_not(None),
        )
    )
    tool_call_arrays = [row[0] for row in tool_result.all() if isinstance(row[0], list)]
    tool_counts = [len(arr) for arr in tool_call_arrays]
    avg_tool_calls = sum(tool_counts) / len(tool_counts) if tool_counts else 0.0

    # Per-tool stats: count occurrences per tool name across all events,
    # then compute avg calls per event for each tool.
    per_tool_totals: dict[str, int] = {}
    for arr in tool_call_arrays:
        for tc in arr:
            if isinstance(tc, dict):
                name = tc.get("name")
                if isinstance(name, str):
                    per_tool_totals[name] = per_tool_totals.get(name, 0) + 1
    n_events_with_tools = max(len(tool_call_arrays), 1)
    tool_stats = {
        name: {
            "total_calls": total,
            "avg_calls": round(total / n_events_with_tools, 3),
        }
        for name, total in per_tool_totals.items()
    }

    baseline = {
        "avg_token_count": float(row.avg_token_count),
        "std_token_count": float(row.std_token_count),
        "avg_latency_ms": float(row.avg_latency_ms),
        "std_latency_ms": float(row.std_latency_ms),
        "avg_tool_calls": avg_tool_calls,
        "tool_stats": tool_stats,
        "known_models": known_models,
        "event_count": event_count,
        "computed_at": datetime.now(UTC).isoformat(),
        "quality": classify_quality(event_count),
    }

    log.info(
        "baseline.computed",
        agent_id=str(agent_id),
        event_count=event_count,
        avg_tokens=baseline["avg_token_count"],
        avg_latency=baseline["avg_latency_ms"],
        models=known_models,
    )

    return baseline
