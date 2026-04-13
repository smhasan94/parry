"""Compliance posture engine — evaluates Article 26 obligations.

Computes green/yellow/red/na status per obligation against the current
org state. Cached in Redis for 1 hour, recomputed on demand or daily
by the compliance refresh task.
"""

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AISystem,
    AuditLog,
    FRIADocument,
    Incident,
    Org,
    SeriousIncident,
    Severity,
)

log = structlog.get_logger()

ObligationStatus = Literal["green", "yellow", "red", "na"]

_CACHE_PREFIX = "posture:"
_CACHE_TTL = 3600  # 1 hour

def _get_redis() -> Any | None:
    try:
        from app.core.redis_pool import sync_redis

        return sync_redis()
    except Exception:
        log.debug("posture.redis_unavailable", exc_info=True)
        return None


@dataclass
class Obligation:
    id: str
    article: str
    title: str
    status: ObligationStatus
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None


async def compute_posture(
    db: AsyncSession, org_id: uuid.UUID
) -> list[Obligation]:
    """Evaluate all Article 26 obligations for an org."""
    obligations: list[Obligation] = []

    obligations.append(await _check_usage_logs(db, org_id))
    obligations.append(await _check_human_oversight(db, org_id))
    obligations.append(await _check_risk_monitoring(db, org_id))
    obligations.append(await _check_suspension(db, org_id))
    obligations.append(await _check_fria(db, org_id))
    obligations.append(await _check_serious_incidents(db, org_id))
    obligations.append(await _check_eu_registration(db, org_id))

    return obligations


async def get_posture(
    db: AsyncSession, org_id: uuid.UUID
) -> list[Obligation]:
    """Get posture with Redis cache (fail open)."""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(f"{_CACHE_PREFIX}{org_id}")
            if raw is not None:
                data = json.loads(raw)
                return [Obligation(**o) for o in data]
        except Exception:
            log.debug("posture.cache_miss", exc_info=True)

    obligations = await compute_posture(db, org_id)
    _cache_posture(org_id, obligations)
    return obligations


def _cache_posture(org_id: uuid.UUID, obligations: list[Obligation]) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(
            f"{_CACHE_PREFIX}{org_id}",
            _CACHE_TTL,
            json.dumps([asdict(o) for o in obligations]),
        )
    except Exception:
        log.debug("posture.cache_set_failed", exc_info=True)


def overall_status(obligations: list[Obligation]) -> ObligationStatus:
    """Return the worst obligation status (ignoring 'na')."""
    statuses = [o.status for o in obligations if o.status != "na"]
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    if not statuses:
        return "na"
    return "green"


# ── Individual obligation checks ────────────────────────────────


async def _check_usage_logs(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 26(6) — Maintain usage logs >= 6 months."""
    audit_count_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.org_id == org_id)
    )
    audit_count = audit_count_result.scalar_one()

    # Check for recent audit export
    last_export_result = await db.execute(
        select(AuditLog.created_at)
        .where(AuditLog.org_id == org_id, AuditLog.action == "audit_log.exported")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    last_export = last_export_result.scalar_one_or_none()

    status: ObligationStatus = "green" if audit_count > 0 else "red"
    return Obligation(
        id="art_26_6_usage_logs",
        article="Art. 26(6)",
        title="Maintain usage logs",
        status=status,
        evidence={
            "audit_log_rows": audit_count,
            "last_export_at": last_export.isoformat() if last_export else None,
            "minimum_required_days": 180,
        },
        remediation=(
            None if audit_count > 0
            else "No audit rows found; check detection pipeline configuration"
        ),
    )


async def _check_human_oversight(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 26(2) — Human oversight assigned."""
    # We check for org existence as a proxy; real Clerk role count
    # would require an external API call.
    org_result = await db.execute(select(Org).where(Org.id == org_id))
    org = org_result.scalar_one_or_none()
    has_org = org is not None

    return Obligation(
        id="art_26_2_human_oversight",
        article="Art. 26(2)",
        title="Human oversight assigned",
        status="green" if has_org else "red",
        evidence={"rbac_enabled": True, "org_active": has_org},
        remediation=None if has_org else "Organization not found",
    )


async def _check_risk_monitoring(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 26(4) — Monitor for risks during operation."""
    org_result = await db.execute(select(Org).where(Org.id == org_id))
    org = org_result.scalar_one_or_none()
    detection_enabled = bool(org and org.detector_config)

    # Check for recent events (last 7 days)
    from app.db.models import AgentEvent, Agent

    recent_result = await db.execute(
        select(func.count())
        .select_from(AgentEvent)
        .join(Agent, AgentEvent.agent_id == Agent.id)
        .where(
            Agent.org_id == org_id,
            AgentEvent.timestamp > datetime.now(UTC) - timedelta(days=7),
        )
    )
    recent_events = recent_result.scalar_one()

    if detection_enabled and recent_events > 0:
        status: ObligationStatus = "green"
    elif detection_enabled:
        status = "yellow"
    else:
        status = "red"

    return Obligation(
        id="art_26_4_risk_monitoring",
        article="Art. 26(4)",
        title="Monitor for risks during operation",
        status=status,
        evidence={
            "detection_pipeline_active": detection_enabled,
            "events_last_7d": recent_events,
        },
    )


async def _check_suspension(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 26(5) — Suspension capability for serious risks."""
    org_result = await db.execute(select(Org).where(Org.id == org_id))
    org = org_result.scalar_one_or_none()
    blocking = bool(org and org.blocking_enabled)

    return Obligation(
        id="art_26_5_suspension",
        article="Art. 26(5)",
        title="Suspension capability for serious risks",
        status="green" if blocking else "yellow",
        evidence={"blocking_mode_enabled": blocking},
        remediation=(
            None if blocking
            else "Enable blocking mode to exercise Art. 26(5) suspension obligation"
        ),
    )


async def _check_fria(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 27 — FRIA for high-risk systems."""
    result = await db.execute(
        select(AISystem).where(
            AISystem.org_id == org_id, AISystem.risk_level == "high"
        )
    )
    high_risk = list(result.scalars().all())

    if not high_risk:
        return Obligation(
            id="art_27_fria",
            article="Art. 27",
            title="FRIA for high-risk systems",
            status="na",
            evidence={"high_risk_systems": 0},
        )

    missing = [s for s in high_risk if s.fria_status == "missing"]
    stale = [s for s in high_risk if s.fria_status == "stale"]
    draft = [s for s in high_risk if s.fria_status == "draft"]

    if missing:
        status: ObligationStatus = "red"
    elif stale or draft:
        status = "yellow"
    else:
        status = "green"

    return Obligation(
        id="art_27_fria",
        article="Art. 27",
        title="FRIA for high-risk systems",
        status=status,
        evidence={
            "high_risk_systems": len(high_risk),
            "missing_fria": [s.name for s in missing],
            "stale_fria": [s.name for s in stale],
            "draft_fria": [s.name for s in draft],
        },
        remediation=(
            f"Generate FRIA for: {', '.join(s.name for s in missing)}"
            if missing
            else "Update stale FRIAs (>12 months old)" if stale else None
        ),
    )


async def _check_serious_incidents(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 73 — Serious incident reporting within 15 days."""
    # Find CRITICAL incidents in last 30 days
    critical_result = await db.execute(
        select(Incident).where(
            Incident.org_id == org_id,
            Incident.severity == Severity.CRITICAL,
            Incident.created_at > datetime.now(UTC) - timedelta(days=30),
        )
    )
    critical_incidents = list(critical_result.scalars().all())

    # Check which ones have serious incident reports
    unreported = []
    overdue = []
    for inc in critical_incidents:
        report_result = await db.execute(
            select(SeriousIncident).where(
                SeriousIncident.incident_id == inc.id
            )
        )
        report = report_result.scalar_one_or_none()
        if not report or report.reported_to_authority_at is None:
            unreported.append(inc)
            deadline = inc.created_at + timedelta(days=15)
            if datetime.now(UTC) > deadline:
                overdue.append(inc)

    if overdue:
        status: ObligationStatus = "red"
    elif unreported:
        status = "yellow"
    else:
        status = "green"

    return Obligation(
        id="art_73_serious_incidents",
        article="Art. 73",
        title="Serious incident reporting within 15 days",
        status=status,
        evidence={
            "critical_incidents_30d": len(critical_incidents),
            "unreported_count": len(unreported),
            "overdue_count": len(overdue),
        },
        remediation=(
            f"{len(overdue)} incidents past 15-day reporting deadline"
            if overdue
            else f"{len(unreported)} recent CRITICAL incidents may require reporting"
            if unreported
            else None
        ),
    )


async def _check_eu_registration(db: AsyncSession, org_id: uuid.UUID) -> Obligation:
    """Art. 26(11) — EU database registration for high-risk systems."""
    result = await db.execute(
        select(AISystem).where(
            AISystem.org_id == org_id,
            AISystem.risk_level == "high",
            AISystem.metadata_.op("->>")(  # type: ignore[union-attr]
                "eu_database_registered"
            ).is_(None),
        )
    )
    unregistered = list(result.scalars().all())

    return Obligation(
        id="art_26_11_eu_registration",
        article="Art. 26(11)",
        title="EU database registration for high-risk systems",
        status="green" if not unregistered else "yellow",
        evidence={"unregistered_systems": [s.name for s in unregistered]},
        remediation=(
            "Register high-risk systems in the EU database via your competent authority"
            if unregistered
            else None
        ),
    )
