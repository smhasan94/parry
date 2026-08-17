import uuid
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import (
    record_anomaly_drift,
    record_detection_triggered,
    record_incident_created,
)
from app.db.models import Agent, AgentEvent, Detection, Incident, Org, Policy, Severity
from app.services.detector_config_service import merged_config

log = structlog.get_logger()

# CostExploitLoopDetector reads the last 20 entries and needs 10 before it
# fires, so 20 is the whole useful window — loading more just costs I/O.
SESSION_HISTORY_LIMIT = 20

# Upper bound on how far back to look. agent_events is a hypertable; an
# unbounded predicate plans as a scan across every chunk. A cost-exploit
# loop burns its budget in minutes, so an hour is already generous.
SESSION_HISTORY_WINDOW = timedelta(hours=1)


async def run_and_persist_detections(
    db: AsyncSession,
    event: AgentEvent,
) -> list[Detection]:
    """Run all detectors against an event and persist the results.

    This is called by the Celery worker after event ingestion.
    """
    from app.detection.pipeline import DetectionPipeline

    # Build event_data dict for the pipeline
    agent = await db.get(Agent, event.agent_id)
    if agent is None:
        log.warning("detection.agent_not_found", event_id=str(event.id))
        return []

    # Load org policies and detector config for the agent
    policies = await _get_active_policies(db, agent.org_id)
    merged_policy = _merge_policies(policies)
    org_for_config = await db.get(Org, agent.org_id)
    detector_config = merged_config(org_for_config.detector_config if org_for_config else None)

    session_history = await _load_session_history(db, event)

    event_data = {
        "prompt": event.prompt,
        "response": event.response,
        "model": event.model,
        "tool_calls": event.tool_calls or [],
        "latency_ms": event.latency_ms,
        "token_count": event.token_count,
        "baseline": agent.baseline or {},
        "policy": merged_policy,
        "detector_config": detector_config,
        "session_history": session_history,
    }

    pipeline = DetectionPipeline()
    results = await pipeline.run(event_data)

    # Persist detection results
    detections: list[Detection] = []
    triggered_results = [r for r in results if r.triggered]

    for r in results:
        detection = Detection(
            event_id=event.id,
            detector=r.detector,
            severity=r.severity,
            confidence=r.confidence,
            reason=r.reason,
            triggered=r.triggered,
            details=r.details,
        )
        db.add(detection)
        detections.append(detection)
        if r.triggered:
            record_detection_triggered(detector=r.detector, severity=r.severity.value)

        # Observe anomaly drift magnitude on every anomaly detection, even
        # non-triggered ones — the histogram lets us see how close we are
        # to firing and tune thresholds from real traffic.
        if r.detector == "anomaly" and r.details:
            drift = r.details.get("drift") or {}
            quality = r.details.get("baseline_quality") or "unknown"
            sigmas = [
                v for k, v in drift.items() if k.endswith("_sigma") and isinstance(v, int | float)
            ]
            if sigmas:
                record_anomaly_drift(max(sigmas), quality, r.triggered)

    await db.flush()

    # Dispatch webhooks for triggered detections
    for d in detections:
        if d.triggered:
            try:
                from app.services.webhook_dispatch_service import dispatch_event

                await dispatch_event(
                    db,
                    agent.org_id,
                    "detection.triggered",
                    {
                        "detection_id": str(d.id),
                        "detector": d.detector,
                        "severity": d.severity.value,
                        "confidence": d.confidence,
                        "reason": d.reason[:200],
                        "event_id": str(d.event_id),
                        "agent_id": str(agent.id),
                        "agent_name": agent.name,
                    },
                )
            except Exception:
                log.debug("webhook.detection_dispatch_failed", exc_info=True)

    # Dispatch threat intel extraction for high-confidence detections
    for d in detections:
        if d.triggered and d.confidence >= 0.7:
            try:
                from app.workers.threat_intel_task import extract_threat_pattern

                extract_threat_pattern.delay(
                    str(agent.org_id),
                    str(d.id),
                    d.detector,
                    d.severity.value,
                    d.confidence,
                    d.reason,
                )
            except Exception:
                log.debug("threat_intel.dispatch_failed", exc_info=True)

    # Create incident if any detections triggered
    if triggered_results:
        max_severity = pipeline.max_severity(results)
        incident = await _create_or_update_incident(
            db,
            org_id=agent.org_id,
            agent_id=agent.id,
            detections=[d for d in detections if d.triggered],
            severity=max_severity or Severity.MEDIUM,
            trigger_session_id=event.session_id,
            trigger_event_id=event.id,
        )
        log.info(
            "detection.incident_created",
            incident_id=str(incident.id),
            severity=incident.severity.value,
            detection_count=len(triggered_results),
        )
        record_incident_created(severity=incident.severity.value)

        # Dispatch webhook for incident creation
        try:
            from app.services.webhook_dispatch_service import dispatch_event as wh_dispatch

            await wh_dispatch(
                db,
                agent.org_id,
                "incident.created",
                {
                    "incident_id": str(incident.id),
                    "title": incident.title,
                    "severity": incident.severity.value,
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "detection_count": len(triggered_results),
                },
            )
        except Exception:
            log.debug("webhook.incident_dispatch_failed", exc_info=True)

        # Dispatch alerts (Slack, etc.) if the org has alert_config
        from app.core.config import settings
        from app.services.alert_service import dispatch_incident_alert

        org = await db.get(Org, agent.org_id)
        if org:
            try:
                await dispatch_incident_alert(
                    org, incident, dashboard_url=settings.dashboard_url or None
                )
            except Exception as e:
                # Never let alerting failures break detection
                log.warning("alert.dispatch_failed", error=str(e))

    # Auto-generate baseline if agent doesn't have one yet
    if not agent.baseline:
        from app.services.baseline_service import compute_baseline

        baseline = await compute_baseline(db, agent.id)
        if baseline:
            agent.baseline = baseline
            await db.flush()
            log.info(
                "baseline.auto_set",
                agent_id=str(agent.id),
                event_count=baseline["event_count"],
            )

    return detections


async def _load_session_history(
    db: AsyncSession,
    event: AgentEvent,
) -> list[dict[str, Any]]:
    """Load the recent events preceding this one in the same session.

    ``CostExploitLoopDetector`` compares the current event's tool-call
    signature against the last 20 entries and needs at least 10 before
    it will fire, so ``SESSION_HISTORY_LIMIT`` is sized just above that
    window rather than loading the whole session.

    ``agent_events`` is a TimescaleDB hypertable, so this filters on
    ``agent_id`` and a bounded time range — never on ``session_id``
    alone, which would plan as a scan across every chunk.

    Returns plain dicts because detectors are given a JSON-ish
    ``event_data`` mapping, not ORM rows.
    """
    if event.session_id is None:
        return []

    window_start = event.timestamp - SESSION_HISTORY_WINDOW

    result = await db.execute(
        select(AgentEvent)
        .where(
            AgentEvent.agent_id == event.agent_id,
            AgentEvent.session_id == event.session_id,
            AgentEvent.timestamp >= window_start,
            AgentEvent.timestamp <= event.timestamp,
            AgentEvent.id != event.id,
        )
        .order_by(AgentEvent.timestamp.desc())
        .limit(SESSION_HISTORY_LIMIT)
    )
    rows = list(result.scalars().all())

    # Query is newest-first so the LIMIT keeps the most recent events;
    # the detector treats the tail as "recent", so hand it back oldest-first.
    rows.reverse()

    return [
        {
            "tool_calls": row.tool_calls or [],
            "token_count": row.token_count,
            "model": row.model,
        }
        for row in rows
    ]


async def _get_active_policies(db: AsyncSession, org_id: uuid.UUID) -> list[Policy]:
    result = await db.execute(
        select(Policy).where(Policy.org_id == org_id, Policy.is_active.is_(True))
    )
    return list(result.scalars().all())


def _merge_policies(policies: list[Policy]) -> dict[str, Any]:
    """Merge all active policies into a single policy dict for the detector."""
    merged: dict[str, Any] = {
        "allowed_tools": [],
        "blocked_tools": [],
        "allowed_domains": [],
        "blocked_domains": [],
        "forbidden_patterns": [],
    }
    for p in policies:
        if p.allowed_tools:
            merged["allowed_tools"].extend(p.allowed_tools)
        if p.blocked_tools:
            merged["blocked_tools"].extend(p.blocked_tools)
        if p.allowed_domains:
            merged["allowed_domains"].extend(p.allowed_domains)
        if p.blocked_domains:
            merged["blocked_domains"].extend(p.blocked_domains)
        if p.forbidden_patterns:
            merged["forbidden_patterns"].extend(p.forbidden_patterns)
        if p.max_token_budget:
            existing = merged.get("max_token_budget")
            if existing is None or p.max_token_budget < existing:
                merged["max_token_budget"] = p.max_token_budget

    # Deduplicate
    for key in ("allowed_tools", "blocked_tools", "allowed_domains", "blocked_domains"):
        merged[key] = list(set(merged[key])) if merged[key] else []

    return merged


async def _create_or_update_incident(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    detections: list[Detection],
    severity: Severity,
    trigger_session_id: uuid.UUID | None = None,
    trigger_event_id: uuid.UUID | None = None,
) -> Incident:
    """Create a new incident grouping the triggered detections.

    ``trigger_session_id`` / ``trigger_event_id`` are stashed in
    ``metadata`` so the dashboard can deep-link to the session replay
    without needing a new column on the incidents table.
    """
    top_detection = max(detections, key=lambda d: d.confidence)
    title = f"[{severity.value.upper()}] {top_detection.detector}: {top_detection.reason}"

    metadata: dict[str, Any] = {}
    if trigger_session_id is not None:
        metadata["trigger_session_id"] = str(trigger_session_id)
    if trigger_event_id is not None:
        metadata["trigger_event_id"] = str(trigger_event_id)

    incident = Incident(
        org_id=org_id,
        agent_id=agent_id,
        title=title,
        severity=severity,
        metadata_=metadata or None,
    )
    db.add(incident)
    await db.flush()

    # Link detections to incident
    for d in detections:
        d.incident_id = incident.id
    await db.flush()

    return incident
