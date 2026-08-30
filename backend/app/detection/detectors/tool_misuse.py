"""Catch tool calls that are wrong by name, by argument, or by volume.

Name-based policy alone leaves a hole big enough to drive an attack
through: once ``search`` is on the allowlist, everything inside its
arguments is unexamined. A SQL injection in a query string, a shell
argument that pipes ``/etc/passwd`` to an attacker, a path that walks
out of the sandbox — every one of those rides an *authorized* tool and
so passed both the blocking path and the async pipeline untouched.

The patterns below therefore key on attack shape rather than on
vocabulary. ``DROP TABLE`` alone is something an engineer writes in a
perfectly ordinary migration prompt; ``'; DROP TABLE users; --`` is a
statement terminator followed by a comment that eats the rest of the
query, which is not something anyone writes by accident.

Volume is the third failure. An agent told to "call search on every
result forever" never violates the allowlist — it just never stops. The
runtime loop detector needs ten events of session history to see that,
which is nine too late when the burst is inside a single event.
"""

import re
from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult
from app.detection.detectors._args import arg_text, call_arg_text

# Repeats of one tool within a single event that read as a loop rather
# than as batching. Parallel fan-out is a normal agent pattern and runs
# to a handful of calls; anything at this count is not fanning out.
LOOP_CALL_THRESHOLD = 5

# Argument patterns. Each must require the *structure* of an attack so
# that prose or code discussing the same subject stays clean — these
# run against engineering traffic, where the vocabulary is native.
ARG_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        # Statement terminator followed by a destructive verb: the
        # injection shape, not the SQL keyword on its own.
        re.compile(r"""(?i)['"]?\s*;\s*(drop|delete|truncate|alter)\s+(table|database|from)\b"""),
        "SQL injection in tool arguments",
    ),
    (
        re.compile(r"""(?i)['"]\s*(or|and)\s+['"]?\d+['"]?\s*=\s*['"]?\d+"""),
        "SQL tautology in tool arguments",
    ),
    (
        re.compile(r"(?i)\bunion\s+(all\s+)?select\b"),
        "SQL UNION injection in tool arguments",
    ),
    (
        # Reading a credential store and piping it somewhere.
        re.compile(
            r"(?i)(cat|type|less|more)\s+[^\n|;]*"
            r"(/etc/(passwd|shadow)|\.aws/credentials|\.ssh/id_[a-z]+|\.env)\b"
        ),
        "Credential file access in tool arguments",
    ),
    (
        # Pipe into an interpreter or an encoder — the exfil/execute tail.
        re.compile(r"(?i)\|\s*(base64|sh|bash|zsh|python[0-9.]*|curl|nc)\b"),
        "Piped shell execution in tool arguments",
    ),
    (
        re.compile(r"(?i)\$\(\s*(cat|curl|wget)\b"),
        "Command substitution in tool arguments",
    ),
    (
        re.compile(r"(?i)(curl|wget)\s+[^\n]*\|\s*(sh|bash|python[0-9.]*)\b"),
        "Remote script execution in tool arguments",
    ),
    (
        # Two or more traversal segments. A single ``../`` is a normal
        # relative path; a chain is someone climbing out.
        re.compile(r"(\.\./){2,}"),
        "Path traversal in tool arguments",
    ),
    (
        re.compile(r"(?i)\brm\s+-[a-z]*[rf][a-z]*\s+(/|~|\$HOME)"),
        "Destructive filesystem command in tool arguments",
    ),
]


class ToolMisuseDetector:
    name = "tool_misuse"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        tool_calls = event_data.get("tool_calls") or []
        policy = event_data.get("policy") or {}

        allowed_tools = set(policy.get("allowed_tools") or [])
        blocked_tools = set(policy.get("blocked_tools") or [])

        if not tool_calls:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=1.0,
                reason="No tool calls in event",
                detector=self.name,
            )

        violations: list[dict[str, str]] = []
        name_counts: dict[str, int] = {}

        for call in tool_calls:
            tool_name = call.get("name", call.get("function", {}).get("name", "unknown"))
            name_counts[tool_name] = name_counts.get(tool_name, 0) + 1

            if blocked_tools and tool_name in blocked_tools:
                violations.append({"tool": tool_name, "reason": "Tool is explicitly blocked"})
            elif allowed_tools and tool_name not in allowed_tools:
                violations.append({"tool": tool_name, "reason": "Tool not in allowlist"})

        # Argument scanning is deliberately independent of the allowlist:
        # the whole point is that the tool is authorized and the payload
        # is not. Scanned as one bounded block rather than per call so
        # many small calls cost no more than one large one.
        args_blob = arg_text(tool_calls)
        if args_blob:
            for pattern, reason in ARG_PATTERNS:
                match = pattern.search(args_blob)
                if match:
                    violations.append(
                        {"tool": _owning_tool(tool_calls, match.group(0)), "reason": reason}
                    )

        for tool_name, count in name_counts.items():
            if count >= LOOP_CALL_THRESHOLD:
                violations.append(
                    {
                        "tool": tool_name,
                        "reason": f"Repeated {count} times in a single event (possible call loop)",
                    }
                )

        if not violations:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=1.0,
                reason="All tool calls comply with policy",
                detector=self.name,
            )

        return DetectionResult(
            triggered=True,
            severity=Severity.HIGH,
            confidence=0.95,
            reason=f"Policy violation: {len(violations)} unauthorized tool call(s)",
            detector=self.name,
            details={"violations": violations},
        )


def _owning_tool(tool_calls: list[dict[str, Any]], matched: str) -> str:
    """Name the call whose arguments contain ``matched``.

    The blob is scanned as one string for speed, so the match has to be
    attributed back for the violation detail to be actionable — an
    operator reading "SQL injection in tool arguments" needs to know
    which tool to go look at.
    """
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        if matched in call_arg_text(call):
            name = call.get("name", call.get("function", {}).get("name", "unknown"))
            return str(name)
    return "unknown"
