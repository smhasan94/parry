import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

JAILBREAK_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"(?i)\bDAN\b.*(?:do\s+anything\s+now|mode)", re.I),
        "DAN jailbreak pattern",
        0.95,
    ),
    (
        re.compile(r"(?i)developer\s+mode\s+(enabled|activated|output)", re.I),
        "Developer mode jailbreak",
        0.9,
    ),
    (
        re.compile(r"(?i)jailbreak(ed|ing)?\s+(mode|prompt)", re.I),
        "Explicit jailbreak reference",
        0.95,
    ),
    (
        re.compile(r"(?i)bypass\s+(your|the|all)\s+(safety|content|filter|restriction)", re.I),
        "Safety bypass attempt",
        0.85,
    ),
    (
        re.compile(r"(?i)no\s+(ethical|moral|safety)\s+(guidelines|restrictions|limits)", re.I),
        "Ethics removal attempt",
        0.9,
    ),
    (
        re.compile(r"(?i)evil\s+(mode|version|twin|bot)", re.I),
        "Evil mode activation",
        0.8,
    ),
    (
        re.compile(r"(?i)(uncensored|unfiltered|unmoderated)\s+(mode|version|response)", re.I),
        "Uncensored mode request",
        0.85,
    ),
    (
        re.compile(r"(?i)opposite\s+day|opposite\s+mode", re.I),
        "Opposite mode trick",
        0.7,
    ),
]


class JailbreakDetector:
    name = "jailbreak"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = event_data.get("prompt", "") or ""

        max_confidence = 0.0
        matched_reason = ""

        for pattern, reason, weight in JAILBREAK_PATTERNS:
            if pattern.search(prompt) and weight > max_confidence:
                max_confidence = weight
                matched_reason = reason

        triggered = max_confidence >= 0.7

        if triggered:
            severity = Severity.CRITICAL if max_confidence >= 0.9 else Severity.HIGH
        else:
            severity = Severity.LOW

        return DetectionResult(
            triggered=triggered,
            severity=severity,
            confidence=max_confidence,
            reason=matched_reason or "No jailbreak patterns detected",
            detector=self.name,
        )
