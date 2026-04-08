"""Session replay — assembles an ordered event timeline for a session.

Used by the dashboard's session replay page. Verifies the session
belongs to the caller's org before returning anything, loads every
event for the session in timestamp order, and joins detections via
event_id (no hypertable FK so we can't do it in a single query).

Role-aware content gating: viewers see previews only, admins see full
prompt + response. The plan explicitly calls this out so analysts can
do forensics while default roles can't exfil raw prompts.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentEvent, AgentSession, Detection

log = structlog.get_logger()

PREVIEW_CHARS = 200
SESSION_LIST_DEFAULT_LIMIT = 20
SESSION_LIST_MAX_LIMIT = 100


def _preview(value: str | None, limit: int = PREVIEW_CHARS) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


async def _load_session_and_agent(
    db: AsyncSession, session_id: uuid.UUID, org_id: uuid.UUID
) -> tuple[AgentSession, Agent] | None:
    """Fetch session + parent agent, verifying org ownership."""
    stmt = (
        select(AgentSession, Agent)
        .join(Agent, AgentSession.agent_id == Agent.id)
        .where(AgentSession.id == session_id, Agent.org_id == org_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    return row[0], row[1]


async def _load_detections_for_events(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Detection]]:
    """Group detections by event_id. Detection.event_id has no FK into
    the hypertable, so a straight JOIN isn't possible — this is the
    cheapest way to fan detections onto their events.
    """
    if not event_ids:
        return {}
    result = await db.execute(select(Detection).where(Detection.event_id.in_(event_ids)))
    grouped: dict[uuid.UUID, list[Detection]] = {}
    for detection in result.scalars().all():
        grouped.setdefault(detection.event_id, []).append(detection)
    return grouped


def _serialize_event(
    event: AgentEvent,
    detections: list[Detection],
    include_content: bool,
) -> dict[str, Any]:
    """Render a single event for the replay timeline.

    When ``include_content`` is False (viewer role) only previews are
    returned; admins get the full prompt + response text.
    """
    payload: dict[str, Any] = {
        "id": str(event.id),
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "model": event.model,
        "latency_ms": event.latency_ms,
        "token_count": event.token_count,
        "tool_calls": event.tool_calls or [],
        "prompt_preview": _preview(event.prompt),
        "response_preview": _preview(event.response),
        "detections": [
            {
                "id": str(d.id),
                "detector": d.detector,
                "severity": d.severity.value,
                "confidence": d.confidence,
                "reason": d.reason,
                "triggered": d.triggered,
            }
            for d in sorted(detections, key=lambda d: d.confidence, reverse=True)
        ],
    }
    if include_content:
        payload["prompt"] = event.prompt
        payload["response"] = event.response
    return payload


async def get_session_with_events(
    db: AsyncSession,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    include_content: bool = False,
) -> dict[str, Any] | None:
    """Return the full session replay payload, or ``None`` when not found.

    ``None`` is used instead of raising so the route handler can turn
    it into a 404 with the same message whether the session is missing
    or belongs to a different org (no org-existence disclosure).
    """
    loaded = await _load_session_and_agent(db, session_id, org_id)
    if loaded is None:
        return None
    session, agent = loaded

    event_result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.session_id == session_id)
        .order_by(AgentEvent.timestamp.asc())
    )
    events: list[AgentEvent] = list(event_result.scalars().all())
    event_ids = [e.id for e in events]
    detections_by_event = await _load_detections_for_events(db, event_ids)

    triggered_count = 0
    for evt in events:
        for d in detections_by_event.get(evt.id, []):
            if d.triggered:
                triggered_count += 1

    return {
        "session": {
            "id": str(session.id),
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "started_at": session.created_at.isoformat() if session.created_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "event_count": len(events),
            "triggered_detection_count": triggered_count,
            "metadata": session.metadata_ or {},
        },
        "events": [
            _serialize_event(
                e,
                detections_by_event.get(e.id, []),
                include_content=include_content,
            )
            for e in events
        ],
    }


async def list_agent_sessions(
    db: AsyncSession,
    agent_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    limit: int = SESSION_LIST_DEFAULT_LIMIT,
) -> list[dict[str, Any]] | None:
    """Return recent sessions for an agent (newest first).

    Returns ``None`` when the agent doesn't exist in this org so the
    route can produce a 404. Each entry carries the event count for
    its session — cheap enough via a grouped count and avoids N+1.
    """
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    ).scalar_one_or_none()
    if agent is None:
        return None

    capped = max(1, min(limit, SESSION_LIST_MAX_LIMIT))

    sessions = (
        (
            await db.execute(
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id)
                .order_by(AgentSession.created_at.desc())
                .limit(capped)
            )
        )
        .scalars()
        .all()
    )
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    count_rows = await db.execute(
        select(AgentEvent.session_id, func.count())
        .where(
            AgentEvent.agent_id == agent_id,
            AgentEvent.session_id.in_(session_ids),
        )
        .group_by(AgentEvent.session_id)
    )
    counts: dict[uuid.UUID, int] = {sid: int(c) for sid, c in count_rows.all() if sid is not None}

    return [
        {
            "id": str(s.id),
            "agent_id": str(s.agent_id),
            "started_at": s.created_at.isoformat() if s.created_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "event_count": counts.get(s.id, 0),
            "is_live": s.ended_at is None,
        }
        for s in sessions
    ]
