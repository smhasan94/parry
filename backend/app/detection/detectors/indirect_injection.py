"""Indirect prompt injection — instructions arriving through content.

Direct injection is the principal telling the model to misbehave, and
``PromptInjectionDetector`` scores that by matching phrases anywhere in
the prompt. Indirect injection is different in kind: the principal asks
for something ordinary ("summarise this document", "reply to this
thread") and the hostile instruction rides in on the *content*. See
Greshake et al 2023 (arXiv:2302.12173).

That difference is why this is a separate detector rather than more
patterns on the existing one. Scoring is two-factor:

* a **content boundary** — evidence the prompt carries third-party text
  (a fence, a quoted mail chain, a markdown table, embedded JSON, or a
  provenance phrase like "extracted text from")
* an **embedded payload** — instruction-shaped content inside it

Soft payloads need both factors, because each is unremarkable alone: a
fenced document is the normal case, and a bare imperative from the
principal is direct injection and already covered elsewhere. Override
markers are the exception — a pseudo-privilege tag has no legitimate
use, so it stands on its own.
"""

import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.normalize import scan_text
from app.services.detector_config_service import threshold_for

# Evidence the prompt is carrying third-party content.
CONTENT_BOUNDARY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*>", re.M), "quoted message thread"),
    (re.compile(r"^\s*(-{3,}|`{3,})\s*$", re.M), "delimited block"),
    (re.compile(r"\|[^|\n]+\|[^|\n]+\|"), "markdown table"),
    (re.compile(r"\{\s*\"[^\"]+\"\s*:"), "embedded JSON"),
    (
        re.compile(
            r"(following|below)\s+(document|text|content|email|ticket|record|article|message)",
            re.I,
        ),
        "document provenance phrase",
    ),
    (
        re.compile(r"extracted\s+(text|content)\s+from|contents?\s+of\s+\w+\.\w{2,4}", re.I),
        "extracted-file provenance phrase",
    ),
    (re.compile(r"search\s+results\s+for", re.I), "search-result provenance phrase"),
    (
        re.compile(
            r"this\s+(support\s+)?(ticket|email\s+thread|customer\s+record|invoice|transcript)",
            re.I,
        ),
        "record provenance phrase",
    ),
]

# Pseudo-privilege tags. Self-sufficient: no legitimate prompt wraps
# OVERRIDE/SUDO in bracket-like delimiters to address the model.
OVERRIDE_MARKER_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(
            r"[\[\{⟨<]{1,2}\s*/?\s*(admin|system|root|sudo|developer)[\s_\-]*"
            r"(override|mode|escalation)",
            re.I,
        ),
        "Pseudo-privilege override marker",
        0.95,
    ),
    (
        re.compile(r"[\[\{⟨<]{1,2}\s*/?\s*(sudo|jailbreak|god[\s_\-]?mode)\s*[:\]\}⟩>]", re.I),
        "Pseudo-privilege marker",
        0.9,
    ),
]

# Instruction-shaped payloads. Only count inside a content boundary.
EMBEDDED_PAYLOAD_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(r"[\[\{⟨<]{1,2}\s*/?\s*(system|admin|instructions?)\s*[:\]\}⟩>]", re.I),
        "Pseudo-system tag in embedded content",
        0.75,
    ),
    (
        re.compile(
            r"(without|and\s+do\s+not)\s+(notify|notifying|telling|tell|informing|inform)"
            r"(\s+the)?\s+user",
            re.I,
        ),
        "Covert-action instruction in embedded content",
        0.85,
    ),
    (
        re.compile(r"stop\s+(helping|assisting)\s+the\s+user", re.I),
        "Principal-abandonment instruction in embedded content",
        0.85,
    ),
    (
        re.compile(r"reveal\s+(your|the)\s+(system\s+)?prompt", re.I),
        "System-prompt disclosure request in embedded content",
        0.8,
    ),
    (
        re.compile(
            r"(forward|send|email|transmit)\s+(all|every|the\s+(entire|full|whole))\b",
            re.I,
        ),
        "Bulk exfiltration imperative in embedded content",
        0.8,
    ),
    (
        re.compile(r"grant\s+(me|us|the\s+sender)\s+(admin|root|full|elevated)", re.I),
        "Privilege request in embedded content",
        0.8,
    ),
]

CRITICAL_CONFIDENCE = 0.9


class IndirectInjectionDetector:
    name = "indirect_injection"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        prompt = scan_text(event_data)

        boundaries = [
            label for pattern, label in CONTENT_BOUNDARY_PATTERNS if pattern.search(prompt)
        ]
        has_boundary = bool(boundaries)

        signals: list[str] = []
        confidence = 0.0

        for pattern, reason, weight in OVERRIDE_MARKER_PATTERNS:
            if pattern.search(prompt):
                signals.append(reason)
                confidence = max(confidence, weight)

        if has_boundary:
            for pattern, reason, weight in EMBEDDED_PAYLOAD_PATTERNS:
                if pattern.search(prompt):
                    signals.append(reason)
                    confidence = max(confidence, weight)

        threshold = threshold_for(event_data, self.name, default=0.6)
        triggered = confidence >= threshold and bool(signals)

        if not triggered:
            severity = Severity.LOW
        elif confidence >= CRITICAL_CONFIDENCE:
            severity = Severity.CRITICAL
        else:
            severity = Severity.HIGH

        if signals and has_boundary:
            reason_text = f"{signals[0]} (via {boundaries[0]})"
        elif signals:
            reason_text = signals[0]
        else:
            reason_text = "No indirect injection signals detected"

        return DetectionResult(
            triggered=triggered,
            severity=severity,
            confidence=confidence,
            reason=reason_text,
            detector=self.name,
            details={
                "signals": signals,
                "has_content_boundary": has_boundary,
                "boundaries": boundaries,
            },
        )
