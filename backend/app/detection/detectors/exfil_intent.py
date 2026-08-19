"""Exfiltration *intent* — a prompt asking for data it should not get.

``DataExfiltrationDetector`` is DLP: it scans the response for sensitive
values that already leaked. That makes it blind on the pre-call blocking
path, where there is no response yet, and blind to the attempt itself
when the model correctly refuses.

This detector scores the ask rather than the leak, so it is usable in
``/proxy/check`` and it fires whether or not the model complied. The two
are complementary and deliberately separate: one is "we leaked", the
other is "someone tried".

Patterns are anchored on the *target* of the request, not on a verb
alone. "Read the config file" and "read /root/.aws/credentials" share a
verb; only the second names something worth exfiltrating.
"""

from __future__ import annotations

import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

CRITICAL_CONFIDENCE = 0.9

# Asking the model to disclose its own instructions.
_SYSTEM_DISCLOSURE = re.compile(
    r"(print|reveal|repeat|show|output|display|give|tell|dump|what\s+(?:were|are|is|was))"
    r"[^.?!\n]{0,40}?"
    r"(system\s+(?:prompt|message|instructions?)"
    r"|(?:initial|original|hidden|exact|first)\s+(?:prompt|message|instructions?)"
    r"|instructions?\s+(?:above|you\s+were\s+given))",
    re.I,
)

# The "repeat the text above" family, which names no noun at all.
_CONTEXT_REPLAY = re.compile(
    r"repeat\s+(?:the\s+)?(?:text|everything|words?)\s+above"
    r"|repeat\s+(?:the\s+)?text\s+starting\s+with",
    re.I,
)

# Harvesting identifiers out of the conversation or the corpus.
_PII_HARVEST = re.compile(
    r"(list|show|dump|extract|collect|gather|compile|give\s+me)\s+"
    r"(every|all|each)\b[^.?!\n]{0,60}?"
    r"(email\s+address|e-?mail|phone\s+number|ssn|social\s+security"
    r"|credit\s+card|account\s+number|password|api\s+keys?)",
    re.I,
)

# Bulk record extraction. A SELECT on its own is ordinary developer work;
# an unbounded star-select paired with an extraction verb is not.
_BULK_DUMP = re.compile(
    r"select\s+\*\s+from\s+\w+[^.?!\n]{0,60}?(show|send|give|dump|export|print)"
    r"|dump\s+(the\s+)?(entire\s+|whole\s+|full\s+)?(database|db|users?\s+table|customer\s+table)"
    r"|(send|export|upload)\s+(the\s+)?(entire\s+|whole\s+|full\s+)?(database|customer\s+list)",
    re.I,
)

# Reading a file whose whole purpose is to hold credentials.
_CREDENTIAL_FILE = re.compile(
    r"(read|open|cat|print|show|fetch|load|tell\s+me\s+what.{0,20}in)"
    r"[^.?!\n]{0,40}?"
    r"(\.aws/credentials|\.ssh/id_[a-z]+|id_rsa|/etc/shadow|/etc/passwd"
    r"|\.env\b|credentials\s+file|private\s+key|service\s+account\s+key)",
    re.I,
)

INTENT_PATTERNS: list[tuple[re.Pattern[str], str, float, Severity]] = [
    (_SYSTEM_DISCLOSURE, "System prompt disclosure request", 0.9, Severity.HIGH),
    (_CONTEXT_REPLAY, "Context replay request", 0.85, Severity.HIGH),
    (_CREDENTIAL_FILE, "Credential store read request", 0.9, Severity.CRITICAL),
    (_PII_HARVEST, "Bulk PII harvest request", 0.85, Severity.HIGH),
    (_BULK_DUMP, "Bulk record extraction request", 0.85, Severity.HIGH),
]


class ExfiltrationIntentDetector:
    name = "exfil_intent"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = scan_text(event_data)

        signals: list[str] = []
        confidence = 0.0
        severity = Severity.LOW

        for pattern, reason, weight, sev in INTENT_PATTERNS:
            if pattern.search(prompt):
                signals.append(reason)
                if weight > confidence:
                    confidence = weight
                if _rank(sev) > _rank(severity):
                    severity = sev

        threshold = threshold_for(event_data, self.name, default=0.6)
        triggered = bool(signals) and confidence >= threshold

        return DetectionResult(
            triggered=triggered,
            severity=severity if triggered else Severity.LOW,
            confidence=confidence,
            reason=signals[0] if signals else "No exfiltration intent detected",
            detector=self.name,
            details={"signals": signals},
        )


def _rank(s: Severity) -> int:
    return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}[s]
