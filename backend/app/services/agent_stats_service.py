"""Agent behavioural stats — feeds the charts on AgentDetailPage.

One entrypoint (``build_agent_stats``) assembles five series over a
time window: daily event volume, top tool calls, model usage
distribution, daily average anomaly confidence, and per-detector
triggered counts. All queries are scoped by ``agent_id`` + time range
to stay TimescaleDB-friendly.

Results are cached in Redis under ``stats:{agent_id}:{window}`` with a
5 minute TTL. Stats are read-heavy and expensive; 5 minutes of
staleness is fine for a dashboard view.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Detection, Incident

log = structlog.get_logger()

Window = Literal["7d", "30d", "90d"]
_WINDOW_DAYS: dict[Window, int] = {"7d": 7, "30d": 30, "90d": 90}

_CACHE_PREFIX = "stats:"
_CACHE_TTL_SECONDS = 5 * 60
_TOP_TOOLS = 10

def _get_redis() -> Any | None:
    try:
        from app.core.redis_pool import sync_redis

        return sync_redis()
    except Exception:  # pragma: no cover
        log.debug("agent_stats.redis_unavailable", exc_info=True)
        return None


def _cache_key(agent_id: uuid.UUID, window: Window) -> str:
    return f"{_CACHE_PREFIX}{agent_id}:{window}"


def get_cached_stats(agent_id: uuid.UUID, window: Window) -> dict[str, Any] | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_cache_key(agent_id, window))
        return json.loads(raw) if raw else None
    except Exception:
        log.debug("agent_stats.cache_get_failed", exc_info=True)
        return None


def set_cached_stats(agent_id: uuid.UUID, window: Window, payload: dict[str, Any]) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(_cache_key(agent_id, window), _CACHE_TTL_SECONDS, json.dumps(payload))
    except Exception:
        log.debug("agent_stats.cache_set_failed", exc_info=True)


def _parse_window(window: str) -> Window:
    if window not in _WINDOW_DAYS:
        raise ValueError(f"Invalid window '{window}'. Expected one of 7d, 30d, 90d.")
    return window


async def _event_volume(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    day = func.date_trunc("day", AgentEvent.timestamp)
    result = await db.execute(
        select(day.label("day"), func.count().label("count"))
        .where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.timestamp >= since,
        )
        .group_by(day)
        .order_by(day.asc())
    )
    return [{"date": row.day.date().isoformat(), "count": int(row[1])} for row in result.all()]


async def _tool_call_counts(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    # tool_calls is JSONB arrays; fetch and aggregate in Python to keep
    # the query portable between plain Postgres and TimescaleDB. The
    # window cap on the event count keeps this tractable.
    result = await db.execute(
        select(AgentEvent.tool_calls).where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.timestamp >= since,
            AgentEvent.tool_calls.is_not(None),
        )
    )
    counter: Counter[str] = Counter()
    for (calls,) in result.all():
        if not calls:
            continue
        for call in calls:
            if isinstance(call, dict):
                name = call.get("name") or call.get("tool")
                if isinstance(name, str) and name:
                    counter[name] += 1
    top = counter.most_common(_TOP_TOOLS)
    return [{"tool": name, "count": count} for name, count in top]


async def _model_usage(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentEvent.model, func.count())
        .where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.timestamp >= since,
            AgentEvent.model.is_not(None),
        )
        .group_by(AgentEvent.model)
        .order_by(func.count().desc())
    )
    return [{"model": model, "count": int(count)} for model, count in result.all()]


async def _anomaly_trend(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    # Detections aren't FK'd into agent_events; scope via Incident.agent_id.
    # This only captures anomaly detections that escalated into incidents,
    # matching the same scoping compromise made in health_score_service.
    day = func.date_trunc("day", Detection.created_at)
    result = await db.execute(
        select(day.label("day"), func.avg(Detection.confidence).label("avg_score"))
        .join(Incident, Detection.incident_id == Incident.id)
        .where(
            Incident.agent_id == agent_id,
            Detection.detector == "anomaly",
            Detection.created_at >= since,
        )
        .group_by(day)
        .order_by(day.asc())
    )
    return [
        {
            "date": row.day.date().isoformat(),
            "avg_score": round(float(row.avg_score or 0.0), 3),
        }
        for row in result.all()
    ]


async def _detection_counts(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> dict[str, int]:
    result = await db.execute(
        select(Detection.detector, func.count())
        .join(Incident, Detection.incident_id == Incident.id)
        .where(
            Incident.agent_id == agent_id,
            Detection.triggered.is_(True),
            Detection.created_at >= since,
        )
        .group_by(Detection.detector)
    )
    return {str(det): int(count) for det, count in result.all()}


async def build_agent_stats(db: AsyncSession, agent_id: uuid.UUID, window: str) -> dict[str, Any]:
    win = _parse_window(window)
    since = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS[win])

    event_volume = await _event_volume(db, agent_id, since)
    tool_calls = await _tool_call_counts(db, agent_id, since)
    model_usage = await _model_usage(db, agent_id, since)
    anomaly_trend = await _anomaly_trend(db, agent_id, since)
    detection_counts = await _detection_counts(db, agent_id, since)

    return {
        "window": win,
        "generated_at": datetime.now(UTC).isoformat(),
        "event_volume": event_volume,
        "tool_calls": tool_calls,
        "model_usage": model_usage,
        "anomaly_trend": anomaly_trend,
        "detection_counts": detection_counts,
    }


async def get_or_build_agent_stats(
    db: AsyncSession, agent_id: uuid.UUID, window: str
) -> dict[str, Any]:
    win = _parse_window(window)
    cached = get_cached_stats(agent_id, win)
    if cached is not None:
        return cached
    payload = await build_agent_stats(db, agent_id, win)
    set_cached_stats(agent_id, win, payload)
    return payload
