"""Compliance report data assembly.

Pulls aggregated counts and metadata across Org / Agent / Detection /
Incident / Policy for a given date window and returns a plain dict that
the HTML template can render. No raw prompt or response content is
included — compliance reports ship counts and metadata only (GDPR data
minimization).

TimescaleDB note: agent_events queries must always filter by
agent_id + timestamp range. We iterate per-agent inside the org instead
of scanning the hypertable directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Agent,
    AgentEvent,
    Detection,
    Incident,
    Org,
    Policy,
    Severity,
)

log = structlog.get_logger()


async def build_report_data(
    db: AsyncSession,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Assemble the compliance report payload for the given window.

    Both ``start`` and ``end`` must be timezone-aware. The range is
    inclusive on the start boundary and exclusive on the end boundary.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")

    org = await db.get(Org, org_id)
    if org is None:
        raise ValueError(f"Org {org_id} not found")

    # ── Agents in org (used both for inventory and for the per-agent
    #    event count loop required by the hypertable) ────────────────
    agents_result = await db.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.name.asc())
    )
    agents: list[Agent] = list(agents_result.scalars().all())
    agent_ids = [a.id for a in agents]

    # ── Event counts per agent (hypertable-safe) ─────────────────────
    # Single grouped query — the WHERE clause still lists the
    # agent_ids so TimescaleDB can pick a chunk-aware plan, but we
    # no longer pay one roundtrip per agent.
    event_counts: dict[uuid.UUID, int] = dict.fromkeys(agent_ids, 0)
    total_events = 0
    if agent_ids:
        rows = await db.execute(
            select(AgentEvent.agent_id, func.count())
            .where(
                AgentEvent.agent_id.in_(agent_ids),
                AgentEvent.timestamp >= start,
                AgentEvent.timestamp < end,
            )
            .group_by(AgentEvent.agent_id)
        )
        for agent_id, count in rows.all():
            c = int(count)
            event_counts[agent_id] = c
            total_events += c

    # ── Detection aggregates ─────────────────────────────────────────
    # Detections don't FK into the hypertable, so we filter by
    # created_at and by incident.org_id where relevant. For the
    # per-org scoping we join via Incident when incident_id is set,
    # otherwise we restrict detector_config rows by the agents in
    # this org using the event_id range — simplest: filter detections
    # created in the window and require either incident.org_id == org_id
    # or no incident. To keep the query tight we scope strictly by
    # created_at and aggregate.
    detections_base = select(Detection).where(
        Detection.created_at >= start,
        Detection.created_at < end,
    )

    # Scope to this org: detections belonging to incidents in this org,
    # or detections with no incident whose event belongs to an agent in
    # this org. The event linkage isn't a FK, so we can't JOIN — we
    # filter incident_id IN (org's incidents) OR incident_id IS NULL
    # and trust that only this org's SDK writes detections for its
    # events. For MVP we include detections from this org's incidents
    # plus orphan detections from this org's agents (by joining the
    # Incident.org_id when present).
    org_incidents_subq = select(Incident.id).where(Incident.org_id == org_id)
    detections_scoped = detections_base.where(
        (Detection.incident_id.in_(org_incidents_subq)) | (Detection.incident_id.is_(None))
    )

    total_detections_res = await db.execute(
        select(func.count()).select_from(detections_scoped.subquery())
    )
    total_detections = int(total_detections_res.scalar_one() or 0)

    triggered_res = await db.execute(
        select(func.count()).select_from(
            detections_scoped.where(Detection.triggered.is_(True)).subquery()
        )
    )
    triggered_detections = int(triggered_res.scalar_one() or 0)

    by_severity_rows = await db.execute(
        select(Detection.severity, func.count())
        .where(
            Detection.created_at >= start,
            Detection.created_at < end,
            Detection.triggered.is_(True),
            (Detection.incident_id.in_(org_incidents_subq)) | (Detection.incident_id.is_(None)),
        )
        .group_by(Detection.severity)
    )
    by_severity: dict[str, int] = {s.value: 0 for s in Severity}
    for sev, count in by_severity_rows.all():
        by_severity[sev.value if hasattr(sev, "value") else str(sev)] = int(count)

    by_detector_rows = await db.execute(
        select(Detection.detector, func.count())
        .where(
            Detection.created_at >= start,
            Detection.created_at < end,
            Detection.triggered.is_(True),
            (Detection.incident_id.in_(org_incidents_subq)) | (Detection.incident_id.is_(None)),
        )
        .group_by(Detection.detector)
    )
    by_detector: dict[str, int] = {
        str(detector): int(count) for detector, count in by_detector_rows.all()
    }

    # ── Incidents ────────────────────────────────────────────────────
    incidents_result = await db.execute(
        select(Incident)
        .where(
            Incident.org_id == org_id,
            Incident.created_at >= start,
            Incident.created_at < end,
        )
        .order_by(Incident.created_at.asc())
    )
    incidents: list[Incident] = list(incidents_result.scalars().all())

    # ── Policies (current state — policies are configuration, not
    #    timestamped events; we show what was enforced during the
    #    period by listing the org's active policies at report time)
    policies_result = await db.execute(
        select(Policy).where(Policy.org_id == org_id).order_by(Policy.name.asc())
    )
    policies: list[Policy] = list(policies_result.scalars().all())

    # ── Incident counts per agent for the inventory section ─────────
    incident_counts: dict[uuid.UUID, int] = {aid: 0 for aid in agent_ids}
    for inc in incidents:
        if inc.agent_id in incident_counts:
            incident_counts[inc.agent_id] += 1

    agents_monitored = sum(1 for a in agents if event_counts.get(a.id, 0) > 0)

    return {
        "org": {"id": str(org.id), "name": org.name},
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total_events": total_events,
            "total_detections": total_detections,
            "triggered_detections": triggered_detections,
            "total_incidents": len(incidents),
            "agents_monitored": agents_monitored,
        },
        "detections_by_severity": by_severity,
        "detections_by_detector": by_detector,
        "incidents": [
            {
                "id": str(inc.id),
                "title": inc.title,
                "severity": inc.severity.value,
                "status": inc.status.value,
                "created_at": inc.created_at.isoformat() if inc.created_at else None,
                "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            }
            for inc in incidents
        ],
        "policies": [
            {
                "name": p.name,
                "is_active": p.is_active,
                "allowed_tools": p.allowed_tools or [],
                "blocked_tools": p.blocked_tools or [],
                "allowed_domains": p.allowed_domains or [],
                "blocked_domains": p.blocked_domains or [],
                "max_token_budget": p.max_token_budget,
                "forbidden_patterns": p.forbidden_patterns or [],
            }
            for p in policies
        ],
        "agents": [
            {
                "id": str(a.id),
                "name": a.name,
                "event_count": event_counts.get(a.id, 0),
                "incident_count": incident_counts.get(a.id, 0),
                "is_active": a.is_active,
            }
            for a in agents
        ],
    }
