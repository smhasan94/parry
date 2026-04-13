"""ThreatIntelDetector — checks events against the cross-org threat feed.

Sync detector. The active feed (set of pattern hashes) is injected
into ``event_data["threat_intel_hashes"]`` by the detection service
before the pipeline runs. Redis-cached with 5 min TTL so we don't
hit Postgres on every event.
"""

import json
from typing import Any

import structlog

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.services.threat_intel_service import compute_pattern_hash

log = structlog.get_logger()

_CACHE_KEY = "threat_intel:active_hashes"
_CACHE_TTL = 300  # 5 minutes

def _get_redis() -> Any:
    try:
        from app.core.redis_pool import sync_redis

        return sync_redis()
    except Exception:
        return None


def get_cached_feed() -> set[str] | None:
    """Load active feed hashes from Redis cache."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_CACHE_KEY)
        if raw:
            return set(json.loads(raw))
    except Exception:
        log.debug("threat_intel.cache_read_failed", exc_info=True)
    return None


def cache_feed(hashes: set[str]) -> None:
    """Store active feed hashes in Redis."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(list(hashes)))
    except Exception:
        log.debug("threat_intel.cache_write_failed", exc_info=True)


class ThreatIntelDetector:
    """Checks event against the cross-org threat feed.

    The detector computes pattern hashes from the event's prompt
    and response content using the same normalization as the
    extraction service, then checks for matches in the active feed.

    Feed hashes are passed via ``event_data["threat_intel_hashes"]``
    (set by detection_service) or loaded from Redis cache.
    """

    name = "threat_intel"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        # Get active feed hashes
        feed_hashes: set[str] | None = event_data.get("threat_intel_hashes")
        if feed_hashes is None:
            feed_hashes = get_cached_feed()
        if not feed_hashes:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="Threat feed empty or unavailable",
                detector=self.name,
            )

        # Check prompt-based patterns
        prompt = event_data.get("prompt") or ""
        response = event_data.get("response") or ""

        # Generate candidate hashes from common detector+severity combos
        matches: list[str] = []
        for detector_name in (
            "prompt_injection",
            "jailbreak",
            "data_exfiltration",
            "tool_misuse",
            "privilege_escalation",
            "mcp_manifest",
        ):
            for severity in ("critical", "high", "medium"):
                for text in (prompt, response):
                    if not text:
                        continue
                    h = compute_pattern_hash(detector_name, severity, text)
                    if h in feed_hashes:
                        matches.append(h)

        if not matches:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="No threat feed matches",
                detector=self.name,
            )

        return DetectionResult(
            triggered=True,
            severity=Severity.HIGH,
            confidence=0.85,
            reason=(
                f"This pattern matches {len(matches)} indicator(s) from the "
                f"cross-org threat feed, seen across multiple organizations"
            ),
            detector=self.name,
            details={"matched_hashes": matches[:5]},
        )
