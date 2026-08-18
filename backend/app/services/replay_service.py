"""Incident attack chain replay — forensic timeline for incident investigation.

Reconstructs the sequence of events surrounding an incident trigger,
applies smart windowing to surface the most relevant events, and
annotates each with detections, permission violations, and threat
intel matches.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentEvent,
    Detection,
    Incident,
)

log = structlog.get_logger()

PREVIEW_CHARS = 200
MAX_WINDOW = 50

# Widest page we will pull from the hypertable for one replay. Sits well
# above MAX_WINDOW because _smart_window ranks events against each other,
# so a page narrower than the window it feeds would distort the ranking.
SESSION_EVENT_CAP = 500

# How far either side of the anchor to look. agent_events is partitioned
# on timestamp; without a bound the planner scans every chunk. A session
# is one agent run, so a day either way is already generous.
REPLAY_WINDOW = timedelta(hours=24)

# Relevance scoring weights
SCORE_HAS_DETECTIONS = 3
SCORE_HAS_TOOL_CALLS = 2
SCORE_HIGH_TOKENS = 1
SCORE_NEAR_TRIGGER = 1
NEAR_TRIGGER_RANGE = 5


@dataclass
class EventAnnotation:
    detections: list[dict[str, Any]] = field(default_factory=list)
    permission_violations: list[str] = field(default_factory=list)
    threat_intel_matches: list[str] = field(default_factory=list)
    relevance_score: float = 0.0


@dataclass
class ReplayEvent:
    id: str
    timestamp: str | None
    model: str | None
    prompt_preview: str | None
    response_preview: str | None
    prompt: str | None  # admin only
    response: str | None  # admin only
    tool_calls: list[dict[str, Any]] | None
    token_count: int | None
    is_trigger: bool
    annotations: EventAnnotation


@dataclass
class IncidentReplay:
    incident: dict[str, Any]
    trigger_event_id: str | None
    session_id: str | None
    total_session_events: int
    window_size: int
    events: list[ReplayEvent]


def _preview(text: str | None) -> str | None:
    if text is None:
        return None
    return text[:PREVIEW_CHARS] + "…" if len(text) > PREVIEW_CHARS else text


async def build_incident_replay(
    db: AsyncSession,
    org_id: uuid.UUID,
    incident_id: uuid.UUID,
    include_content: bool = False,
) -> IncidentReplay:
    """Build the full attack chain replay for an incident."""

    # 1. Load incident + detections
    incident = await db.get(Incident, incident_id)
    if incident is None or incident.org_id != org_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Incident", str(incident_id))

    det_result = await db.execute(
        select(Detection)
        .where(
            Detection.incident_id == incident_id,
            Detection.triggered.is_(True),
        )
        .order_by(Detection.confidence.desc())
    )
    detections = list(det_result.scalars().all())

    # 2. Find trigger event (highest confidence detection)
    trigger_event_id: uuid.UUID | None = None
    trigger_detected_at: datetime | None = None
    if detections:
        trigger_event_id = detections[0].event_id
        trigger_detected_at = detections[0].created_at

    # 3. Find the session via trigger event or incident metadata
    #
    # The detection row is written moments after its event is ingested,
    # so its created_at is a tight anchor for the event's own timestamp
    # — which is what the hypertable is partitioned on.
    trigger_event: AgentEvent | None = None
    session_id: uuid.UUID | None = None
    if trigger_event_id:
        trigger_event = await _load_event(
            db, trigger_event_id, near=trigger_detected_at or incident.created_at
        )
        if trigger_event and trigger_event.session_id:
            session_id = trigger_event.session_id

    if session_id is None and incident.metadata_:
        sid = incident.metadata_.get("trigger_session_id")
        if sid:
            session_id = uuid.UUID(sid)

    # 4. Load session events
    if session_id is None:
        # No session — return just the trigger event, already loaded above
        events = [trigger_event] if trigger_event else []
        return IncidentReplay(
            incident=_serialize_incident(incident),
            trigger_event_id=str(trigger_event_id) if trigger_event_id else None,
            session_id=None,
            total_session_events=len(events),
            window_size=len(events),
            events=await _annotate_events(
                db, org_id, events, trigger_event_id, detections, include_content
            ),
        )

    # Load the session's events, bounded to one hypertable slice
    anchor = trigger_event.timestamp if trigger_event else incident.created_at
    all_events, total = await _load_session_events(
        db,
        session_id=session_id,
        agent_id=incident.agent_id,
        anchor=anchor,
    )

    # 5. Smart windowing
    windowed = _smart_window(all_events, trigger_event_id, detections, MAX_WINDOW)

    # 6. Annotate
    annotated = await _annotate_events(
        db, org_id, windowed, trigger_event_id, detections, include_content
    )

    return IncidentReplay(
        incident=_serialize_incident(incident),
        trigger_event_id=str(trigger_event_id) if trigger_event_id else None,
        session_id=str(session_id),
        total_session_events=total,
        window_size=len(annotated),
        events=annotated,
    )


async def _load_event(db: AsyncSession, event_id: uuid.UUID, near: datetime) -> AgentEvent | None:
    """Load one event by id, bounded to a hypertable window.

    ``id`` is only half the composite PK — the partition key is
    ``timestamp``. Without a time bound this lookup scans every chunk.
    ``near`` is the caller's best estimate of when the event landed.
    """
    result = await db.execute(
        select(AgentEvent).where(
            AgentEvent.id == event_id,
            AgentEvent.timestamp >= near - REPLAY_WINDOW,
            AgentEvent.timestamp <= near + REPLAY_WINDOW,
        )
    )
    return result.scalar_one_or_none()


async def _load_session_events(
    db: AsyncSession,
    session_id: uuid.UUID,
    agent_id: uuid.UUID,
    anchor: datetime,
) -> tuple[list[AgentEvent], int]:
    """Load a session's events plus the session's true event count.

    ``agent_events`` is partitioned on ``timestamp``, so a predicate on
    ``session_id`` alone plans as a scan across every chunk. Filtering
    on ``agent_id`` and a ``REPLAY_WINDOW`` around ``anchor`` keeps the
    planner on the chunks that can hold the session.

    The count only costs a second query when the page comes back full;
    a short page is its own count. A session running longer than
    ``REPLAY_WINDOW`` either side of the anchor is truncated, and the
    count reflects the window rather than all time.
    """
    bounds = (
        AgentEvent.agent_id == agent_id,
        AgentEvent.session_id == session_id,
        AgentEvent.timestamp >= anchor - REPLAY_WINDOW,
        AgentEvent.timestamp <= anchor + REPLAY_WINDOW,
    )

    result = await db.execute(
        select(AgentEvent).where(*bounds).order_by(AgentEvent.timestamp).limit(SESSION_EVENT_CAP)
    )
    events = list(result.scalars().all())

    if len(events) < SESSION_EVENT_CAP:
        return events, len(events)

    count_result = await db.execute(select(func.count()).select_from(AgentEvent).where(*bounds))
    return events, count_result.scalar_one()


def _smart_window(
    events: list[AgentEvent],
    trigger_event_id: uuid.UUID | None,
    detections: list[Detection],
    max_size: int,
) -> list[AgentEvent]:
    """Score events by relevance and return top N, re-sorted by timestamp."""
    if len(events) <= max_size:
        return events

    detection_event_ids = {d.event_id for d in detections}

    # Find trigger index for proximity scoring
    trigger_idx: int | None = None
    if trigger_event_id:
        for i, e in enumerate(events):
            if e.id == trigger_event_id:
                trigger_idx = i
                break

    # Compute median token count for relative scoring
    token_counts = [e.token_count for e in events if e.token_count]
    median_tokens = sorted(token_counts)[len(token_counts) // 2] if token_counts else 0

    scored: list[tuple[float, int, AgentEvent]] = []
    for i, event in enumerate(events):
        score = 0.0

        # Has triggered detections
        if event.id in detection_event_ids:
            score += SCORE_HAS_DETECTIONS

        # Has tool calls
        if event.tool_calls:
            score += SCORE_HAS_TOOL_CALLS

        # High token count (above median)
        if event.token_count and median_tokens and event.token_count > median_tokens:
            score += SCORE_HIGH_TOKENS

        # Near the trigger event
        if trigger_idx is not None and abs(i - trigger_idx) <= NEAR_TRIGGER_RANGE:
            score += SCORE_NEAR_TRIGGER

        # Trigger event itself always gets max score
        if trigger_event_id and event.id == trigger_event_id:
            score = 100.0

        scored.append((score, i, event))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = scored[:max_size]

    # Re-sort by original timestamp order
    selected.sort(key=lambda x: x[1])
    return [s[2] for s in selected]


async def _annotate_events(
    db: AsyncSession,
    org_id: uuid.UUID,
    events: list[AgentEvent],
    trigger_event_id: uuid.UUID | None,
    incident_detections: list[Detection],
    include_content: bool,
) -> list[ReplayEvent]:
    """Annotate each event with detections, permissions, threat intel."""
    if not events:
        return []

    event_ids = [e.id for e in events]

    # Load all detections for these events
    det_result = await db.execute(select(Detection).where(Detection.event_id.in_(event_ids)))
    det_by_event: dict[uuid.UUID, list[Detection]] = {}
    for d in det_result.scalars().all():
        det_by_event.setdefault(d.event_id, []).append(d)

    # Load active threat intel hashes (best effort)
    threat_hashes: set[str] = set()
    try:
        from app.services.threat_intel_service import get_active_pattern_hashes

        threat_hashes = await get_active_pattern_hashes(db)
    except Exception:
        pass

    # Load agent permission for tool call annotation
    agent_ids = {e.agent_id for e in events}
    permissions: dict[uuid.UUID, Any] = {}
    try:
        from app.services.permission_service import get_permission

        for aid in agent_ids:
            perm = await get_permission(db, org_id, aid)
            if perm:
                permissions[aid] = perm
    except Exception:
        pass

    result: list[ReplayEvent] = []
    for event in events:
        is_trigger = trigger_event_id is not None and event.id == trigger_event_id
        event_dets = det_by_event.get(event.id, [])

        annotation = EventAnnotation()

        # Detection annotations
        for d in event_dets:
            annotation.detections.append(
                {
                    "detector": d.detector,
                    "severity": d.severity.value,
                    "confidence": d.confidence,
                    "reason": d.reason,
                    "triggered": d.triggered,
                }
            )

        # Permission violation check
        if event.tool_calls and event.agent_id in permissions:
            perm = permissions[event.agent_id]
            from app.services.permission_service import evaluate_permission

            for tc in event.tool_calls:
                tool_name = tc.get("name") or tc.get("function", {}).get("name")
                if tool_name:
                    pr = evaluate_permission(perm, tool_name, str(event.agent_id))
                    if not pr.allowed:
                        annotation.permission_violations.append(f"{tool_name}: {pr.reason}")

        # Threat intel check
        if threat_hashes and (event.prompt or event.response):
            from app.services.threat_intel_service import compute_pattern_hash

            for detector_name in ("prompt_injection", "jailbreak", "data_exfiltration"):
                for severity in ("critical", "high"):
                    for text in (event.prompt, event.response):
                        if not text:
                            continue
                        h = compute_pattern_hash(detector_name, severity, text)
                        if h in threat_hashes:
                            annotation.threat_intel_matches.append(h[:16])

        # Relevance score
        score = 0.0
        if annotation.detections:
            score += SCORE_HAS_DETECTIONS
        if event.tool_calls:
            score += SCORE_HAS_TOOL_CALLS
        if is_trigger:
            score = 10.0
        annotation.relevance_score = score

        result.append(
            ReplayEvent(
                id=str(event.id),
                timestamp=event.timestamp.isoformat() if event.timestamp else None,
                model=event.model,
                prompt_preview=_preview(event.prompt),
                response_preview=_preview(event.response),
                prompt=event.prompt if include_content else None,
                response=event.response if include_content else None,
                tool_calls=event.tool_calls,
                token_count=event.token_count,
                is_trigger=is_trigger,
                annotations=annotation,
            )
        )

    return result


def _serialize_incident(incident: Incident) -> dict[str, Any]:
    return {
        "id": str(incident.id),
        "title": incident.title,
        "severity": incident.severity.value,
        "status": incident.status.value,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
    }


# ── Pure functions for testing ──────────────────────────────────


def score_event(
    event_has_detections: bool,
    event_has_tool_calls: bool,
    token_count_above_median: bool,
    distance_from_trigger: int | None,
    is_trigger: bool,
) -> float:
    """Pure scoring function exposed for unit testing."""
    if is_trigger:
        return 100.0
    score = 0.0
    if event_has_detections:
        score += SCORE_HAS_DETECTIONS
    if event_has_tool_calls:
        score += SCORE_HAS_TOOL_CALLS
    if token_count_above_median:
        score += SCORE_HIGH_TOKENS
    if distance_from_trigger is not None and distance_from_trigger <= NEAR_TRIGGER_RANGE:
        score += SCORE_NEAR_TRIGGER
    return score
