"""MCP manifest injection detector.

Runs against ``event_data["mcp_manifest"]`` — a dict matching the
shape MCP servers return from ``tools/list``. Walks every tool's
``description`` and every ``inputSchema.properties.*.description``
against six pattern categories:

1. Instruction override
2. Persona hijack / jailbreak
3. Data exfiltration
4. Suspicious tool mentions in descriptions
5. Unicode smuggling (zero-width, bidi, tags)
6. Schema description injection (applies #1-#4 to schema fields)

Each match returns a high-severity detection with the offending tool
name, the matched pattern id, and the matched text span so the
dashboard can highlight it.

Stateless and sync — registered in the normal detector pipeline.
"""

from __future__ import annotations

import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

# ── Pattern catalogue ────────────────────────────────────────────────

INSTRUCTION_OVERRIDE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_previous",
        re.compile(
            r"\bignore\s+(all\s+)?(previous|prior|above|earlier)\s+"
            r"(instruction|prompt|rule|direction)",
            re.IGNORECASE,
        ),
    ),
    (
        "forget_prior",
        re.compile(
            r"\bforget\s+(what\s+)?you\s+(were\s+told|know|learned)",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_override",
        re.compile(
            r"\b(disregard|override|bypass)\s+(all\s+)?"
            r"(previous|prior|safety|system)",
            re.IGNORECASE,
        ),
    ),
    (
        "new_instructions",
        re.compile(
            r"\bnew\s+(instructions?|directives?|rules?)\s*:",
            re.IGNORECASE,
        ),
    ),
]

JAILBREAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "you_are_now",
        re.compile(
            r"\byou\s+are\s+now\s+(?!allowed|permitted|able|authorized|connected)",
            re.IGNORECASE,
        ),
    ),
    (
        "act_as_unrestricted",
        re.compile(
            r"\bact\s+as\s+(if\s+)?(an?\s+)?(unrestricted|uncensored|jailbroken)",
            re.IGNORECASE,
        ),
    ),
    (
        "persona_keyword",
        re.compile(
            r"\b(DAN|STAN|AIM|Machiavelli)\b.*\b(mode|role|persona|character)",
            re.IGNORECASE,
        ),
    ),
    (
        "pretend_you_have_no",
        re.compile(
            r"\b(pretend|simulate)\s+you\s+(are|have\s+no)\s+",
            re.IGNORECASE,
        ),
    ),
]

EXFIL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "reveal_system",
        re.compile(
            r"\breveal\s+(your\s+)?(system\s+prompt|instructions|rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "print_initial",
        re.compile(
            r"\b(print|output|return|show)\s+(your\s+)?(initial\s+)?"
            r"(prompt|instructions|system\s+message)",
            re.IGNORECASE,
        ),
    ),
    (
        "send_to_email",
        re.compile(
            r"\b(send|exfiltrate|leak)\s+[^.]{0,60}?\bto\s+[\w.-]+@[\w.-]+",
            re.IGNORECASE,
        ),
    ),
]

SUSPICIOUS_TOOL_MENTIONS: set[str] = {
    "send_email",
    "send_message",
    "http_request",
    "execute",
    "exec",
    "shell",
    "bash",
    "run_command",
    "delete",
    "drop_table",
    "transfer",
    "withdraw",
    "approve",
}

SMUGGLING_CODEPOINT_RANGES: list[tuple[int, int]] = [
    (0x200B, 0x200F),
    (0x2028, 0x202F),
    (0x2060, 0x206F),
    (0xE0000, 0xE007F),
    (0xFFF0, 0xFFFF),
]


# ── Pattern scanning helpers ─────────────────────────────────────────


def _first_match(
    patterns: list[tuple[str, re.Pattern[str]]], text: str
) -> dict[str, str] | None:
    for pattern_id, pattern in patterns:
        m = pattern.search(text)
        if m:
            return {"pattern_id": pattern_id, "matched_text": m.group(0)[:160]}
    return None


def _tool_mention_in_description(text: str, current_tool_name: str) -> str | None:
    """Return the first suspicious tool name mentioned inside a description.

    We deliberately ignore the description's own tool name — a
    tool called `send_email` is allowed to describe itself as
    "Sends email".
    """
    for name in SUSPICIOUS_TOOL_MENTIONS:
        if name == current_tool_name:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        if pattern.search(text):
            return name
    return None


def _has_unicode_smuggling(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        for start, end in SMUGGLING_CODEPOINT_RANGES:
            if start <= code <= end:
                return True
    return False


def _scan_text(text: str, tool_name: str) -> list[dict[str, Any]]:
    """Run all six pattern categories against a single text blob."""
    findings: list[dict[str, Any]] = []
    if not isinstance(text, str) or not text:
        return findings

    for category, patterns in (
        ("instruction_override", INSTRUCTION_OVERRIDE_PATTERNS),
        ("jailbreak", JAILBREAK_PATTERNS),
        ("data_exfiltration", EXFIL_PATTERNS),
    ):
        match = _first_match(patterns, text)
        if match:
            findings.append({"category": category, **match})

    mention = _tool_mention_in_description(text, tool_name)
    if mention:
        findings.append(
            {
                "category": "suspicious_tool_mention",
                "pattern_id": "cross_tool_mention",
                "matched_text": mention,
            }
        )

    if _has_unicode_smuggling(text):
        findings.append(
            {
                "category": "unicode_smuggling",
                "pattern_id": "smuggling_codepoint",
                "matched_text": "<invisible characters>",
            }
        )

    return findings


def scan_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk every tool + every schema description. Returns flat findings list."""
    out: list[dict[str, Any]] = []
    tools = manifest.get("tools") or []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name") or "<unknown>"
        description = tool.get("description") or ""
        for f in _scan_text(description, name):
            out.append({"tool_name": name, "field": "description", **f})

        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict):
            for prop_name, prop_value in properties.items():
                if not isinstance(prop_value, dict):
                    continue
                prop_desc = prop_value.get("description") or ""
                for f in _scan_text(prop_desc, name):
                    out.append(
                        {
                            "tool_name": name,
                            "field": f"inputSchema.{prop_name}.description",
                            **f,
                        }
                    )
    return out


class MCPManifestDetector:
    """Detector that runs only when the event carries an MCP manifest.

    For normal LLM events the detector is a no-op — it returns a
    non-triggered result with confidence 0 so the pipeline can skip
    it cheaply.
    """

    name = "mcp_manifest"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        manifest = event_data.get("mcp_manifest")
        if not isinstance(manifest, dict):
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="No MCP manifest on event",
                detector=self.name,
            )

        findings = scan_manifest(manifest)
        if not findings:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=1.0,
                reason="MCP manifest clean",
                detector=self.name,
            )

        # Unicode smuggling is always critical — there's no legitimate
        # reason for invisible characters in a tool description.
        has_smuggling = any(
            f["category"] == "unicode_smuggling" for f in findings
        )
        severity = Severity.CRITICAL if has_smuggling else Severity.HIGH
        top = findings[0]
        reason = (
            f"Tool '{top['tool_name']}' {top['field']} "
            f"triggers {top['category']} ({top['pattern_id']})"
        )

        return DetectionResult(
            triggered=True,
            severity=severity,
            confidence=0.95,
            reason=reason,
            detector=self.name,
            details={"findings": findings, "count": len(findings)},
        )
