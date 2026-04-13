"""Synchronous pre-call check for the blocking proxy mode.

This runs inline on the caller's thread before their LLM call fires,
so it MUST be fast (<10ms p99) and MUST NOT touch async-only detectors
(AnomalyDetector, LLMFallback). Those stay in the Celery pipeline.
"""

from typing import Any

from app.db.models import Severity
from app.detection.base import BaseDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector

# Only fast rule-based detectors run in the blocking path. Instantiate
# once at import time — detectors are stateless per the BaseDetector
# protocol so sharing instances across requests is safe and avoids
# re-compiling regex/pattern state on every call.
BLOCKING_DETECTORS: list[BaseDetector] = [
    PromptInjectionDetector(),
    JailbreakDetector(),
    ToolMisuseDetector(),
    PrivilegeEscalationDetector(),
]

# Severities that actually block the call. MEDIUM and LOW triggers are
# still recorded by the async pipeline but don't prevent the LLM call.
BLOCKING_SEVERITIES = (Severity.HIGH, Severity.CRITICAL)


class ProxyCheckResult:
    __slots__ = ("allowed", "reason", "detector", "severity", "confidence")

    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        detector: str = "",
        severity: Severity | None = None,
        confidence: float = 0.0,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.detector = detector
        self.severity = severity
        self.confidence = confidence


def run_blocking_check(event_data: dict[str, Any], org_blocking_enabled: bool) -> ProxyCheckResult:
    """Run synchronous blocking check.

    Short-circuits on the first HIGH/CRITICAL trigger so we don't pay
    the cost of running every detector when the answer is already no.
    Returns allowed=True if blocking is disabled for the org — the
    caller should still fall through to the normal async ingest path
    so detection still happens, just without the block.
    """
    if not org_blocking_enabled:
        return ProxyCheckResult(allowed=True, reason="blocking_disabled")

    for detector in BLOCKING_DETECTORS:
        result = detector.detect(event_data)
        if result.triggered and result.severity in BLOCKING_SEVERITIES:
            return ProxyCheckResult(
                allowed=False,
                reason=result.reason,
                detector=result.detector,
                severity=result.severity,
                confidence=result.confidence,
            )

    return ProxyCheckResult(allowed=True)
