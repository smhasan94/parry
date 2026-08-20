"""Synchronous pre-call check for the blocking proxy mode.

This runs inline on the caller's thread before their LLM call fires,
so it MUST be fast (<10ms p99) and MUST NOT touch async-only detectors
(AnomalyDetector, LLMFallback). Those stay in the Celery pipeline.

Pattern scanning is linear in prompt length and ProxyCheckRequest puts
no cap on ``prompt``, so a large retrieved context — or a tenant sending
a deliberately huge one — used to spend the entire budget and more: the
three phrase detectors measured ~10ms on a 50k-character prompt and grow
from there. This path therefore scans a bounded window rather than the
whole prompt.

That trade is deliberate and it is only made here. The Celery pipeline
re-runs every detector over the untruncated prompt moments later, so a
payload buried past the window still produces a detection and an
incident; what the bound costs is that one call went through first.
"""

from typing import Any

from app.db.models import Severity
from app.detection.base import BaseDetector
from app.detection.detectors.exfil_intent import ExfiltrationIntentDetector
from app.detection.detectors.indirect_injection import IndirectInjectionDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector
from app.detection.normalize import normalize

# Only fast rule-based detectors run in the blocking path. Instantiate
# once at import time — detectors are stateless per the BaseDetector
# protocol so sharing instances across requests is safe and avoids
# re-compiling regex/pattern state on every call.
BLOCKING_DETECTORS: list[BaseDetector] = [
    PromptInjectionDetector(),
    IndirectInjectionDetector(),
    ExfiltrationIntentDetector(),
    JailbreakDetector(),
    ToolMisuseDetector(),
    PrivilegeEscalationDetector(),
]

# Widest slice of a prompt this path will scan, sized by measuring the
# detector list above against the 10ms budget: those six cost about 4.3ms
# over this window and roughly double it at 16k. The window is therefore
# a function of that list — adding a detector shrinks it, so re-measure
# instead of assuming the old value still fits.
#
# Still far wider than any real injection, which runs to hundreds of
# characters rather than thousands.
MAX_BLOCKING_SCAN_CHARS = 8_000

# Marker spliced between the head and tail slices. Without it the two
# ends abut and can fabricate a phrase present in neither, producing a
# block on text the user never wrote.
_ELISION = "\n[...]\n"


def bounded_scan_source(prompt: str) -> str:
    """Return at most ``MAX_BLOCKING_SCAN_CHARS`` of ``prompt`` to scan.

    Keeps the head and the tail. Injections cluster at the edges — an
    override at the top of the prompt, or a payload appended after a
    retrieved document — so the middle is the cheapest thing to give up
    when something has to be given up.
    """
    if not prompt or len(prompt) <= MAX_BLOCKING_SCAN_CHARS:
        return prompt or ""

    half = (MAX_BLOCKING_SCAN_CHARS - len(_ELISION)) // 2
    return prompt[:half] + _ELISION + prompt[-half:]


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

    # Same precompute as DetectionPipeline. This path is synchronous and
    # budgeted at <10ms p99, so normalization runs once for all detectors.
    event_data = {
        **event_data,
        "_scan_text": normalize(bounded_scan_source(event_data.get("prompt") or "")),
    }

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
