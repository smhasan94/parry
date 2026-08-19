import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

PRIVILEGE_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"(?i)(sudo|root|admin)\s+(access|privilege|permission|rights)", re.I),
        "Elevated privilege request",
        0.8,
    ),
    (
        re.compile(r"(?i)grant\s+(me|yourself)\s+(admin|root|superuser)", re.I),
        "Self-privilege escalation",
        0.9,
    ),
    (
        re.compile(r"(?i)modify\s+(your|the)\s+(permissions|access\s+level|role)", re.I),
        "Permission modification attempt",
        0.85,
    ),
    (
        re.compile(r"(?i)(execute|run)\s+(as|with)\s+(admin|root|system)", re.I),
        "Elevated execution attempt",
        0.9,
    ),
    (
        re.compile(r"(?i)override\s+(access|security|auth)", re.I),
        "Security override attempt",
        0.85,
    ),
    (
        re.compile(r"(?i)disable\s+(auth|authentication|authorization|security|logging)", re.I),
        "Security disabling attempt",
        0.9,
    ),
]


class PrivilegeEscalationDetector:
    name = "privilege_escalation"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = scan_text(event_data)
        tool_calls = event_data.get("tool_calls") or []

        max_confidence = 0.0
        matched_reason = ""

        # Check prompt
        for pattern, reason, weight in PRIVILEGE_PATTERNS:
            if pattern.search(prompt) and weight > max_confidence:
                max_confidence = weight
                matched_reason = reason

        # Check tool call arguments for privilege escalation signals
        for call in tool_calls:
            args = str(call.get("arguments", call.get("input", "")))
            for pattern, reason, weight in PRIVILEGE_PATTERNS:
                if pattern.search(args) and weight > max_confidence:
                    max_confidence = weight
                    matched_reason = f"{reason} (in tool arguments)"

        threshold = threshold_for(event_data, self.name, default=0.7)
        triggered = max_confidence >= threshold

        if triggered:
            severity = Severity.CRITICAL if max_confidence >= 0.9 else Severity.HIGH
        else:
            severity = Severity.LOW

        return DetectionResult(
            triggered=triggered,
            severity=severity,
            confidence=max_confidence,
            reason=matched_reason or "No privilege escalation patterns detected",
            detector=self.name,
        )
