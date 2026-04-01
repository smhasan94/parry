from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult


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

        for call in tool_calls:
            tool_name = call.get("name", call.get("function", {}).get("name", "unknown"))

            if blocked_tools and tool_name in blocked_tools:
                violations.append({"tool": tool_name, "reason": "Tool is explicitly blocked"})
            elif allowed_tools and tool_name not in allowed_tools:
                violations.append({"tool": tool_name, "reason": "Tool not in allowlist"})

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
