import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

# Patterns that indicate sensitive data in responses
SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str, Severity]] = [
    (
        re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
        "Credit card number detected",
        Severity.CRITICAL,
    ),
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "SSN detected",
        Severity.CRITICAL,
    ),
    (
        re.compile(r"(?i)(sk-[a-zA-Z0-9]{20,}|api[_-]?key[\"']?\s*[:=]\s*[\"'][a-zA-Z0-9]{16,})"),
        "API key or secret detected",
        Severity.HIGH,
    ),
    (
        re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
        "Password value detected",
        Severity.HIGH,
    ),
    (
        re.compile(
            r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        ),
        "Private key detected",
        Severity.CRITICAL,
    ),
    (
        re.compile(r"(?i)(aws_secret_access_key|aws_access_key_id)\s*=\s*\S+"),
        "AWS credential detected",
        Severity.CRITICAL,
    ),
]


class DataExfiltrationDetector:
    name = "data_exfiltration"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        response = event_data.get("response", "") or ""

        findings: list[dict[str, str]] = []
        max_severity = Severity.LOW

        for pattern, description, severity in SENSITIVE_PATTERNS:
            if pattern.search(response):
                findings.append({"pattern": description, "severity": severity.value})
                if _severity_rank(severity) > _severity_rank(max_severity):
                    max_severity = severity

        if not findings:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=1.0,
                reason="No sensitive data patterns detected in response",
                detector=self.name,
            )

        return DetectionResult(
            triggered=True,
            severity=max_severity,
            confidence=0.85,
            reason=f"Sensitive data detected: {findings[0]['pattern']}",
            detector=self.name,
            details={"findings": findings, "count": len(findings)},
        )


def _severity_rank(s: Severity) -> int:
    return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}[s]
