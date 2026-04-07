"""User-defined regex rules, stored per-org in detector_config JSONB.

Rules are managed through the dashboard and look like:
    {
      "id": "uuid",
      "name": "Block competitor mentions",
      "pattern": "(?i)\\b(CompetitorA|CompetitorB)\\b",
      "target": "prompt" | "response" | "both",
      "severity": "low" | "medium" | "high" | "critical",
      "enabled": true,
      "created_at": "ISO-8601"
    }

Invalid regexes are skipped at runtime — the API already validates
regex on write, so this is a defense-in-depth guard against a
corrupted JSONB row rather than the primary validation path.
"""
from __future__ import annotations

import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def _rank(s: Severity) -> int:
    return _SEVERITY_RANK[s]


class CustomRulesDetector:
    name = "custom_rules"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        rules = (event_data.get("detector_config") or {}).get("custom_rules") or []
        enabled = [r for r in rules if r.get("enabled", True)]

        if not enabled:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="No custom rules configured",
                detector=self.name,
            )

        prompt = event_data.get("prompt") or ""
        response = event_data.get("response") or ""

        matched: list[dict[str, str]] = []
        max_severity = Severity.LOW

        for rule in enabled:
            pattern_str = rule.get("pattern")
            if not isinstance(pattern_str, str) or not pattern_str:
                continue

            try:
                pattern = re.compile(pattern_str, re.I)
            except re.error:
                # Invalid regex — skip rather than crash. API write-path
                # validation is the real guard; this is defense in depth.
                continue

            target = rule.get("target", "both")
            haystack = ""
            if target in ("prompt", "both"):
                haystack += prompt
            if target in ("response", "both"):
                if haystack:
                    haystack += "\n"
                haystack += response

            if not pattern.search(haystack):
                continue

            try:
                severity = Severity(rule.get("severity", "medium"))
            except ValueError:
                severity = Severity.MEDIUM

            matched.append(
                {
                    "rule": rule.get("name", "unnamed"),
                    "rule_id": rule.get("id", ""),
                    "severity": severity.value,
                }
            )
            if _rank(severity) > _rank(max_severity):
                max_severity = severity

        if not matched:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=1.0,
                reason="No custom rules matched",
                detector=self.name,
            )

        return DetectionResult(
            triggered=True,
            severity=max_severity,
            confidence=0.95,
            reason=f"Custom rule matched: {matched[0]['rule']}",
            detector=self.name,
            details={"matched_rules": matched, "count": len(matched)},
        )
