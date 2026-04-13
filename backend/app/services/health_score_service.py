"""Agent Health Score — a single 0–100 metric per agent.

Synthesises recent triggered detections, open + critical incidents, and
the agent's most recent anomaly-detector confidence into a single
integer. Lower scores mean more evidence of problems. New agents with
no signal score 100 — we don't penalise them for being new.

Scoring (matches docs/plans/plan-04-08-integrations-through-graphs.md):

    health = 100
      - min(triggered_detections_last_7d * 5, 50)
      - min(open_incidents_count * 10, 30)
      - min(critical_incidents_last_30d * 15, 30)
      - int(anomaly_score * 20)
    clamped to [0, 100]

The score is informational only — nothing in the runtime hot path
should ever gate on it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Detection, Incident, IncidentStatus, Severity

log = structlog.get_logger()

# Redis cache: `health:{agent_id}` → JSON health payload. 2h TTL so a
# failing Celery Beat task can't leave the UI permanently stale.
_CACHE_PREFIX = "health:"
_CACHE_TTL_SECONDS = 2 * 60 * 60

_redis_client = None


def _get_redis() -> Any | None:
    """Sync Redis client from shared pool. Returns None on failure (fail open)."""
    try:
        from app.core.redis_pool import sync_redis

        return sync_redis()
    except Exception:  # pragma: no cover - redis lib or URL misconfigured
        log.debug("health_score.redis_unavailable", exc_info=True)
        return None


def get_cached_health(agent_id: uuid.UUID) -> dict[str, Any] | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(f"{_CACHE_PREFIX}{agent_id}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        log.debug("health_score.cache_get_failed", exc_info=True)
        return None


def set_cached_health(agent_id: uuid.UUID, payload: dict[str, Any]) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(
            f"{_CACHE_PREFIX}{agent_id}",
            _CACHE_TTL_SECONDS,
            json.dumps(payload),
        )
    except Exception:
        log.debug("health_score.cache_set_failed", exc_info=True)


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def compute_score(
    *,
    triggered_7d: int,
    open_incidents: int,
    critical_30d: int,
    anomaly_score: float,
) -> tuple[int, str]:
    """Pure scoring function — unit-testable without a DB.

    ``anomaly_score`` is expected in [0, 1]; values outside that range
    are clamped so one rogue detector result can't drive the score
    negative or give an unearned bonus.
    """
    anomaly = max(0.0, min(1.0, float(anomaly_score)))
    penalty = (
        min(triggered_7d * 5, 50)
        + min(open_incidents * 10, 30)
        + min(critical_30d * 15, 30)
        + int(anomaly * 20)
    )
    score = max(0, min(100, 100 - penalty))
    return score, _grade(score)


async def _count_triggered_detections_7d(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> int:
    # Detection has no direct agent_id (event_id points at a TimescaleDB
    # hypertable with no FK). We scope by joining through the
    # Incident.agent_id relationship — triggered detections always get
    # attached to an incident (see detection_service._create_or_update_incident).
    stmt = (
        select(func.count())
        .select_from(Detection)
        .join(Incident, Detection.incident_id == Incident.id)
        .where(
            Incident.agent_id == agent_id,
            Detection.triggered.is_(True),
            Detection.created_at >= since,
        )
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def _count_open_incidents(db: AsyncSession, agent_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Incident)
        .where(
            Incident.agent_id == agent_id,
            Incident.status == IncidentStatus.OPEN,
        )
    )
    return int(result.scalar_one() or 0)


async def _count_critical_incidents_30d(
    db: AsyncSession, agent_id: uuid.UUID, since: datetime
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Incident)
        .where(
            Incident.agent_id == agent_id,
            Incident.severity == Severity.CRITICAL,
            Incident.created_at >= since,
        )
    )
    return int(result.scalar_one() or 0)


async def _latest_anomaly_confidence(db: AsyncSession, agent_id: uuid.UUID) -> float:
    """Most recent anomaly-detector confidence for this agent.

    Best-effort: we only see anomaly Detections that got attached to an
    incident. Non-triggered anomaly detections are recorded but not
    joined to any agent-scoped row, so they're invisible here. That's
    acceptable — the health score is meant to reflect actionable signal,
    not raw drift telemetry. Returns 0.0 when there's nothing to see.
    """
    stmt = (
        select(Detection.confidence)
        .join(Incident, Detection.incident_id == Incident.id)
        .where(
            Incident.agent_id == agent_id,
            Detection.detector == "anomaly",
        )
        .order_by(Detection.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    value = result.scalar_one_or_none()
    return float(value) if value is not None else 0.0


async def compute_health_score(db: AsyncSession, agent_id: uuid.UUID) -> dict[str, Any]:
    """Compute the live health score + component breakdown for an agent."""
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    triggered_7d = await _count_triggered_detections_7d(db, agent_id, seven_days_ago)
    open_incidents = await _count_open_incidents(db, agent_id)
    critical_30d = await _count_critical_incidents_30d(db, agent_id, thirty_days_ago)
    anomaly_score = await _latest_anomaly_confidence(db, agent_id)

    score, grade = compute_score(
        triggered_7d=triggered_7d,
        open_incidents=open_incidents,
        critical_30d=critical_30d,
        anomaly_score=anomaly_score,
    )

    return {
        "score": score,
        "grade": grade,
        "components": {
            "triggered_detections_7d": triggered_7d,
            "open_incidents": open_incidents,
            "critical_incidents_30d": critical_30d,
            "anomaly_score": round(anomaly_score, 3),
        },
        "computed_at": now.isoformat(),
    }


async def get_or_compute_health(db: AsyncSession, agent_id: uuid.UUID) -> dict[str, Any]:
    """Read-through cache: Redis first, live computation on miss.

    On miss we compute live and populate the cache so the next caller
    doesn't pay the query cost. Cache failures always fall through to
    live computation — the score is never load-bearing enough to fail
    a request over a Redis blip.
    """
    cached = get_cached_health(agent_id)
    if cached is not None:
        return cached
    payload = await compute_health_score(db, agent_id)
    set_cached_health(agent_id, payload)
    return payload
