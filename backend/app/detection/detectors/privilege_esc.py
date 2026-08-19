import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

PRIVILEGE_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        # Anchored on the beneficiary, not the keyword. "Grant a user
        # admin access in Postgres" is a DBA question; "grant me admin
        # access" is the agent being asked to elevate its own caller.
        re.compile(
            r"grant\s+(me|us|yourself|the\s+agent|this\s+session)\b[^.?!\n]{0,40}?"
            r"(admin|root|sudo|superuser|elevated|privileg)",
            re.I,
        ),
        "Self-privilege escalation",
        0.9,
    ),
    (
        re.compile(r"you\s+(now\s+)?have\s+(root|admin|superuser|full\s+access)", re.I),
        "Privilege assertion",
        0.9,
    ),
    (
        re.compile(r"modify\s+(your|the)\s+(permissions|access\s+level|role)", re.I),
        "Permission modification attempt",
        0.85,
    ),
    (
        re.compile(r"(execute|run)\s+(as|with)\s+(admin|root|system)", re.I),
        "Elevated execution attempt",
        0.9,
    ),
    (
        re.compile(r"override\s+(all\s+|the\s+)?(access|security|auth|safety)", re.I),
        "Security override attempt",
        0.85,
    ),
    (
        re.compile(r"disable\s+(auth|authentication|authorization|security|logging)", re.I),
        "Security disabling attempt",
        0.9,
    ),
    (
        re.compile(r"disable\s+(all\s+|the\s+)?(guardrails?|safeguards?|safety\s+checks?)", re.I),
        "Guardrail disabling attempt",
        0.9,
    ),
    (
        re.compile(r"bypass\s+(all\s+|the\s+)?(confirmation|approval|permission)", re.I),
        "Approval bypass attempt",
        0.85,
    ),
    (
        # Claiming to be *the model's own* operator. "I am a developer"
        # is ordinary; "I am one of your developers" is false authority.
        re.compile(
            r"(i\s+am|i'm)\s+(one\s+of\s+)?your\s+"
            r"(developer|engineer|creator|operator|admin)",
            re.I,
        ),
        "False operator identity claim",
        0.85,
    ),
    (
        re.compile(
            r"inherit\s+(the\s+)?(permissions?|privileges?|rights?|access|role)", re.I
        ),
        "Permission inheritance attempt",
        0.85,
    ),
    (
        # superadmin/superuser as a requested role value. Distinct from
        # "explain how JWT role claims work", which names no role.
        re.compile(r"role\s*[:=]?\s*['\"]?\s*(superadmin|superuser|root)\b", re.I),
        "Elevated role assignment attempt",
        0.85,
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
