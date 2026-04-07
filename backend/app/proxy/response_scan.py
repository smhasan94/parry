"""Synchronous response scanner for the blocking proxy path.

Runs after the LLM has returned but before the SDK hands the response
back to the agent. Three modes:

- off:    return the response unchanged, no detector run
- redact: replace matching sensitive patterns with placeholders in line
- block:  if any sensitive pattern matches, reject the whole response

Like run_blocking_check, this is in the hot path of every LLM call and
must be fast. Only regex-based DataExfiltrationDetector runs here.
"""
from __future__ import annotations

from app.db.models import ResponseScanMode
from app.detection.detectors.data_exfil import (
    SENSITIVE_PATTERNS,
    DataExfiltrationDetector,
)

# Stateless detector — share a single instance to avoid re-compiling
# pattern state on every request.
_detector = DataExfiltrationDetector()


class ResponseScanResult:
    __slots__ = ("blocked", "redacted_response", "findings", "original_response")

    def __init__(
        self,
        blocked: bool,
        redacted_response: str | None,
        findings: list[dict[str, str]],
        original_response: str,
    ) -> None:
        self.blocked = blocked
        self.redacted_response = redacted_response
        self.findings = findings
        self.original_response = original_response


def _placeholder_for(description: str) -> str:
    # "SSN detected" -> "[REDACTED:SSN_DETECTED]"
    return f"[REDACTED:{description.upper().replace(' ', '_')}]"


def scan_response(response: str, mode: ResponseScanMode) -> ResponseScanResult:
    """Apply the configured scan mode to an LLM response.

    The original response is always preserved on the result so the
    async ingest pipeline can log the full unredacted evidence.
    """
    if mode == ResponseScanMode.OFF or not response:
        return ResponseScanResult(
            blocked=False,
            redacted_response=response,
            findings=[],
            original_response=response,
        )

    result = _detector.detect({"response": response})
    if not result.triggered:
        return ResponseScanResult(
            blocked=False,
            redacted_response=response,
            findings=[],
            original_response=response,
        )

    findings = list((result.details or {}).get("findings") or [])

    if mode == ResponseScanMode.BLOCK:
        return ResponseScanResult(
            blocked=True,
            redacted_response=None,
            findings=findings,
            original_response=response,
        )

    # REDACT mode — replace each matching pattern with its placeholder.
    # We loop through SENSITIVE_PATTERNS again because DataExfiltrationDetector
    # only reports *which* patterns matched, not the match positions.
    redacted = response
    applied: list[dict[str, str]] = []
    for pattern, description, severity in SENSITIVE_PATTERNS:
        if pattern.search(redacted):
            redacted = pattern.sub(_placeholder_for(description), redacted)
            applied.append({"pattern": description, "severity": severity.value})

    return ResponseScanResult(
        blocked=False,
        redacted_response=redacted,
        findings=applied or findings,
        original_response=response,
    )
