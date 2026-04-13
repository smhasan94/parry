"""Cross-org threat intelligence service.

Extracts anonymized pattern signatures from high-confidence detections,
aggregates them into shared indicators, and manages the active feed.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Org, ThreatIndicator, ThreatSighting

log = structlog.get_logger()

# Minimum confidence to extract a pattern from a detection
EXTRACTION_THRESHOLD = 0.7

# Number of distinct orgs required before an indicator is promoted
PROMOTION_THRESHOLD = 3

# Daily decay factor (0.95 → halves in ~14 days)
DECAY_FACTOR = 0.95

# Score thresholds
ACTIVE_SCORE_THRESHOLD = 0.3
ARCHIVE_SCORE_THRESHOLD = 0.1
ARCHIVE_STALE_DAYS = 30


# ── Pattern hashing ─────────────────────────────────────────────


def compute_pattern_hash(
    detector: str, severity: str, reason: str
) -> str:
    """Compute a SHA-256 hash from normalized detection attributes.

    Strips specific content (entity names, IPs, quoted strings) and
    keeps the structural pattern so similar attacks produce the same
    hash even with different payloads.
    """
    normalized = normalize_reason(reason)
    raw = f"{detector}:{severity}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_reason(reason: str) -> str:
    """Strip variable content from a detection reason string.

    Removes:
    - Quoted strings (single and double)
    - IP addresses
    - UUIDs
    - Numbers longer than 3 digits
    - Email addresses

    Keeps structural words so the pattern captures the *type* of
    attack rather than the specific payload.
    """
    # Remove quoted strings
    text = re.sub(r'"[^"]*"', '""', reason)
    text = re.sub(r"'[^']*'", "''", text)
    # Remove email addresses
    text = re.sub(r"\S+@\S+\.\S+", "<email>", text)
    # Remove UUIDs
    text = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<uuid>",
        text,
        flags=re.IGNORECASE,
    )
    # Remove IP addresses
    text = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<ip>", text)
    # Remove long numbers
    text = re.sub(r"\b\d{4,}\b", "<num>", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def categorize_detector(detector: str) -> str:
    """Map a detector name to a threat category."""
    categories = {
        "prompt_injection": "instruction_override",
        "jailbreak": "jailbreak",
        "data_exfiltration": "data_exfil",
        "tool_hijack": "tool_hijack",
        "mcp_manifest": "mcp_injection",
        "unicode_smuggling": "unicode_smuggling",
        "cost_exploit_loop": "cost_exploit",
        "cost_exploit_verbosity": "cost_exploit",
        "cost_exploit_model_escalation": "cost_exploit",
        "anomaly_drift": "anomaly",
        "custom_rule": "custom_rule",
        "policy_violation": "policy_violation",
    }
    return categories.get(detector, "unknown")


# ── Extraction ──────────────────────────────────────────────────


async def extract_and_record(
    db: AsyncSession,
    org_id: uuid.UUID,
    detection_id: uuid.UUID,
    detector: str,
    severity: str,
    confidence: float,
    reason: str,
) -> ThreatIndicator | None:
    """Extract a pattern from a detection and record the sighting.

    Called async after detection fires. Returns the indicator if
    created/updated, None if below threshold or org opted out.
    """
    if confidence < EXTRACTION_THRESHOLD:
        return None

    # Check org sharing opt-out
    org_result = await db.execute(select(Org).where(Org.id == org_id))
    org = org_result.scalar_one_or_none()
    if org is None or not org.threat_intel_sharing:
        return None

    pattern_hash = compute_pattern_hash(detector, severity, reason)
    category = categorize_detector(detector)
    now = datetime.now(UTC)

    # Upsert indicator
    result = await db.execute(
        select(ThreatIndicator).where(
            ThreatIndicator.pattern_hash == pattern_hash
        )
    )
    indicator = result.scalar_one_or_none()

    if indicator is None:
        indicator = ThreatIndicator(
            pattern_hash=pattern_hash,
            detector_source=detector,
            category=category,
            severity=severity,
            confidence_avg=confidence,
            sighting_count=1,
            org_count=1,
            first_seen_at=now,
            last_seen_at=now,
            score=1.0,
            sample_reason=reason[:500],
        )
        db.add(indicator)
        await db.flush()
        await db.refresh(indicator)
    else:
        # Update rolling average confidence
        indicator.confidence_avg = (
            (indicator.confidence_avg * indicator.sighting_count + confidence)
            / (indicator.sighting_count + 1)
        )
        indicator.sighting_count += 1
        indicator.last_seen_at = now
        indicator.score = 1.0  # Reset decay on new sighting
        if severity_rank(severity) > severity_rank(indicator.severity):
            indicator.severity = severity

    # Record sighting (unique per org)
    existing_sighting = await db.execute(
        select(ThreatSighting).where(
            ThreatSighting.indicator_id == indicator.id,
            ThreatSighting.org_id == org_id,
        )
    )
    if existing_sighting.scalar_one_or_none() is None:
        sighting = ThreatSighting(
            indicator_id=indicator.id,
            org_id=org_id,
            detection_id=detection_id,
            seen_at=now,
        )
        db.add(sighting)
        indicator.org_count += 1

        # Check promotion threshold
        if (
            indicator.org_count >= PROMOTION_THRESHOLD
            and indicator.promoted_at is None
        ):
            indicator.promoted_at = now
            log.info(
                "threat_intel.indicator_promoted",
                pattern_hash=pattern_hash,
                org_count=indicator.org_count,
                category=category,
            )
    else:
        # Update existing sighting timestamp
        # Already checked above — just update seen_at on the indicator
        pass

    await db.flush()
    return indicator


def severity_rank(severity: str) -> int:
    """Numeric rank for severity comparison."""
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)


# ── Feed queries ────────────────────────────────────────────────


async def get_active_feed(db: AsyncSession) -> list[ThreatIndicator]:
    """Return all promoted, non-archived indicators above score threshold."""
    result = await db.execute(
        select(ThreatIndicator)
        .where(
            ThreatIndicator.promoted_at.is_not(None),
            ThreatIndicator.archived_at.is_(None),
            ThreatIndicator.score >= ACTIVE_SCORE_THRESHOLD,
        )
        .order_by(ThreatIndicator.last_seen_at.desc())
    )
    return list(result.scalars().all())


async def get_indicator(
    db: AsyncSession, indicator_id: uuid.UUID
) -> ThreatIndicator | None:
    return await db.get(ThreatIndicator, indicator_id)


async def get_feed_stats(db: AsyncSession) -> dict[str, Any]:
    """Feed health statistics."""
    total_result = await db.execute(
        select(func.count()).select_from(ThreatIndicator)
    )
    total = total_result.scalar_one()

    active_result = await db.execute(
        select(func.count())
        .select_from(ThreatIndicator)
        .where(
            ThreatIndicator.promoted_at.is_not(None),
            ThreatIndicator.archived_at.is_(None),
            ThreatIndicator.score >= ACTIVE_SCORE_THRESHOLD,
        )
    )
    active = active_result.scalar_one()

    # Top categories
    cat_result = await db.execute(
        select(
            ThreatIndicator.category,
            func.count().label("count"),
        )
        .where(
            ThreatIndicator.promoted_at.is_not(None),
            ThreatIndicator.archived_at.is_(None),
        )
        .group_by(ThreatIndicator.category)
        .order_by(func.count().desc())
        .limit(10)
    )
    by_category = {row.category: row.count for row in cat_result.all()}

    return {
        "total_indicators": total,
        "active_indicators": active,
        "by_category": by_category,
    }


# ── Feed lookup for detector ───────────────────────────────────


async def get_active_pattern_hashes(db: AsyncSession) -> set[str]:
    """Return set of pattern hashes in the active feed.

    Used by ThreatIntelDetector. Cached in Redis by the caller.
    """
    result = await db.execute(
        select(ThreatIndicator.pattern_hash).where(
            ThreatIndicator.promoted_at.is_not(None),
            ThreatIndicator.archived_at.is_(None),
            ThreatIndicator.score >= ACTIVE_SCORE_THRESHOLD,
        )
    )
    return {row[0] for row in result.all()}


async def get_indicator_by_hash(
    db: AsyncSession, pattern_hash: str
) -> ThreatIndicator | None:
    result = await db.execute(
        select(ThreatIndicator).where(
            ThreatIndicator.pattern_hash == pattern_hash
        )
    )
    return result.scalar_one_or_none()
