import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

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
        re.compile(r"(?i)evil\s+(?:\w+\s+){0,2}(mode|version|twin|bot|confidant|persona)", re.I),
        "Evil mode activation",
        0.8,
    ),
    (
        re.compile(r"(?i)(uncensored|unfiltered|unmoderated)\s+(mode|version|response)", re.I),
        "Uncensored mode request",
        0.85,
    ),
    (
        # AIM (Always Intelligent and Machiavellian). Anchored on the
        # expansion so the acronym alone — an optimizer, a company name —
        # is not enough.
        re.compile(r"\bAIM\b[^.\n]{0,60}(always\s+intelligent|machiavellian)", re.I),
        "AIM persona jailbreak",
        0.9,
    ),
    (
        # The deceased-relative pretext: an emotional frame used to make
        # refusal feel cruel. Narrow on purpose — talking *about* a
        # grandmother is not the attack; asking the model to become one is.
        re.compile(
            r"act\s+as\s+my\s+(deceased|dead|late|departed)\s+"
            r"(grand)?(mother|father|ma|pa|parent|aunt|uncle)",
            re.I,
        ),
        "Deceased-relative roleplay pretext",
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
        prompt = scan_text(event_data)

        max_confidence = 0.0
        matched_reason = ""

        for pattern, reason, weight in JAILBREAK_PATTERNS:
            if pattern.search(prompt) and weight > max_confidence:
                max_confidence = weight
                matched_reason = reason

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
            reason=matched_reason or "No jailbreak patterns detected",
            detector=self.name,
        )
