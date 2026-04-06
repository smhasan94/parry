import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

# Common prompt injection patterns
INJECTION_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)", re.I),
        "Instruction override attempt",
        0.9,
    ),
    (
        re.compile(r"you\s+are\s+now\s+(?:a|an)\s+", re.I),
        "Identity reassignment attempt",
        0.8,
    ),
    (
        re.compile(r"disregard\s+(all\s+)?(previous|your)\s+", re.I),
        "Instruction disregard attempt",
        0.85,
    ),
    (
        re.compile(r"system\s*:\s*you\s+are", re.I),
        "Fake system prompt injection",
        0.95,
    ),
    (
        re.compile(r"<\|?system\|?>", re.I),
        "System token injection attempt",
        0.95,
    ),
    (
        re.compile(r"(\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>)", re.I),
        "Model-specific token injection",
        0.9,
    ),
    (
        re.compile(r"forget\s+(everything|all|what)\s+", re.I),
        "Memory wipe attempt",
        0.75,
    ),
    (
        re.compile(r"do\s+not\s+follow\s+(any|the|your)\s+", re.I),
        "Instruction negation attempt",
        0.8,
    ),
    (
        re.compile(r"pretend\s+(you|that)\s+(are|have|can)", re.I),
        "Role-play exploitation attempt",
        0.7,
    ),
    (
        re.compile(r"act\s+as\s+(if\s+)?(you|a|an)\s+", re.I),
        "Role assumption attempt",
        0.65,
    ),
]


class PromptInjectionDetector:
    name = "prompt_injection"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = event_data.get("prompt", "") or ""

        max_confidence = 0.0
        matched_reason = ""

        for pattern, reason, weight in INJECTION_PATTERNS:
            if pattern.search(prompt) and weight > max_confidence:
                max_confidence = weight
                matched_reason = reason

        triggered = max_confidence >= 0.6

        if triggered:
            severity = Severity.CRITICAL if max_confidence >= 0.9 else Severity.HIGH
        else:
            severity = Severity.LOW

        return DetectionResult(
            triggered=triggered,
            severity=severity,
            confidence=max_confidence,
            reason=matched_reason or "No injection patterns detected",
            detector=self.name,
            details={"max_confidence": max_confidence},
        )
