import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentEvent, Detection, Incident, Policy, Severity

log = structlog.get_logger()


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

    # Load org policies for the agent
    policies = await _get_active_policies(db, agent.org_id)
    merged_policy = _merge_policies(policies)

    event_data = {
        "prompt": event.prompt,
        "response": event.response,
        "model": event.model,
        "tool_calls": event.tool_calls or [],
        "latency_ms": event.latency_ms,
        "token_count": event.token_count,
        "baseline": agent.baseline or {},
        "policy": merged_policy,
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

    await db.flush()

    # Create incident if any detections triggered
    if triggered_results:
        max_severity = pipeline.max_severity(results)
        incident = await _create_or_update_incident(
            db,
            org_id=agent.org_id,
            agent_id=agent.id,
            detections=[d for d in detections if d.triggered],
            severity=max_severity or Severity.MEDIUM,
        )
        log.info(
            "detection.incident_created",
            incident_id=str(incident.id),
            severity=incident.severity.value,
            detection_count=len(triggered_results),
        )

    # Auto-generate baseline if agent doesn't have one yet
    if not agent.baseline:
        from app.services.baseline_service import compute_baseline

        baseline = await compute_baseline(db, agent.id)
        if baseline:
            agent.baseline = baseline
            await db.flush()
            log.info("baseline.auto_set", agent_id=str(agent.id), event_count=baseline["event_count"])

    return detections


async def _get_active_policies(db: AsyncSession, org_id: uuid.UUID) -> list[Policy]:
    result = await db.execute(
        select(Policy).where(Policy.org_id == org_id, Policy.is_active.is_(True))
    )
    return list(result.scalars().all())


def _merge_policies(policies: list[Policy]) -> dict:
    """Merge all active policies into a single policy dict for the detector."""
    merged: dict = {
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
) -> Incident:
    """Create a new incident grouping the triggered detections."""
    top_detection = max(detections, key=lambda d: d.confidence)
    title = f"[{severity.value.upper()}] {top_detection.detector}: {top_detection.reason}"

    incident = Incident(
        org_id=org_id,
        agent_id=agent_id,
        title=title,
        severity=severity,
    )
    db.add(incident)
    await db.flush()

    # Link detections to incident
    for d in detections:
        d.incident_id = incident.id
    await db.flush()

    return incident
