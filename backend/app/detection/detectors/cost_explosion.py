"""Cost exploitation detectors.

Three complementary detectors that catch different flavours of cost
abuse:

- **CostExploitLoopDetector** — detects tight tool-call loops that
  burn tokens without doing useful work (e.g. an injected prompt
  that tells the agent to "keep calling search forever").

- **CostExploitVerbosityDetector** — flags single events whose token
  count is an order of magnitude above the agent's baseline average.

- **CostExploitModelEscalationDetector** — catches an agent that
  silently switched to a much more expensive model than it normally
  uses.
"""

from __future__ import annotations

from typing import Any

from app.core.model_pricing import MODEL_PRICING
from app.db.models import Severity
from app.detection.base import DetectionResult


class CostExploitLoopDetector:
    """Detect repetitive tool-call loops that inflate cost."""

    name = "cost_exploit_loop"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        session_history: list[dict] | None = event_data.get("session_history")

        if not session_history or len(session_history) < 10:
            return self._pass("Insufficient session history")

        # Check that entries actually have tool_calls
        has_tools = any(e.get("tool_calls") for e in session_history)
        if not has_tools:
            return self._pass("No tool calls in session history")

        # Compare current event's tool call signature with recent 20
        current_tc = event_data.get("tool_calls") or []
        if not current_tc:
            return self._pass("Current event has no tool calls")

        current_sig = self._tool_call_signature(current_tc)
        recent = session_history[-20:]

        identical_count = 0
        for entry in recent:
            sig = self._tool_call_signature(entry.get("tool_calls") or [])
            if sig == current_sig:
                identical_count += 1

        ratio = identical_count / len(recent) if recent else 0

        if identical_count >= 10 and ratio >= 0.5:
            return DetectionResult(
                triggered=True,
                severity=Severity.MEDIUM,
                confidence=min(0.6 + ratio * 0.3, 0.95),
                reason=(
                    f"Repetitive tool-call loop detected: {identical_count}/{len(recent)} "
                    f"recent calls share the same signature (ratio={ratio:.2f})"
                ),
                detector=self.name,
                details={
                    "identical_count": identical_count,
                    "window_size": len(recent),
                    "ratio": round(ratio, 3),
                    "signature": list(current_sig),
                },
            )

        return self._pass("No repetitive loop pattern detected")

    @staticmethod
    def _tool_call_signature(tool_calls: list) -> tuple[str, ...]:
        """Canonical signature: sorted tuple of tool names."""
        names: list[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("name")
                if isinstance(name, str):
                    names.append(name)
        return tuple(sorted(names))

    def _pass(self, reason: str) -> DetectionResult:
        return DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason=reason,
            detector=self.name,
        )


class CostExploitVerbosityDetector:
    """Detect single events with abnormally high token usage."""

    name = "cost_exploit_verbosity"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        token_count = event_data.get("token_count")
        baseline = event_data.get("baseline") or {}
        avg_token_count = baseline.get("avg_token_count")

        if not token_count or not avg_token_count:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="Missing token count or baseline",
                detector=self.name,
            )

        ratio = token_count / avg_token_count if avg_token_count > 0 else 0

        if ratio >= 10:
            return DetectionResult(
                triggered=True,
                severity=Severity.MEDIUM,
                confidence=min(0.6 + (ratio - 10) * 0.02, 0.95),
                reason=(
                    f"Token count {token_count} is {ratio:.1f}x the baseline "
                    f"average ({avg_token_count:.0f})"
                ),
                detector=self.name,
                details={
                    "token_count": token_count,
                    "baseline_avg": avg_token_count,
                    "ratio": round(ratio, 2),
                },
            )

        return DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason="Token count within normal range",
            detector=self.name,
        )


class CostExploitModelEscalationDetector:
    """Detect an agent switching to a significantly more expensive model."""

    name = "cost_exploit_model_escalation"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        model = event_data.get("model")
        baseline = event_data.get("baseline") or {}
        known_models: list[str] = baseline.get("known_models") or []

        if not model or not known_models:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="Missing model or baseline known_models",
                detector=self.name,
            )

        current_pricing = MODEL_PRICING.get(model)
        if current_pricing is None:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason=f"Unknown model '{model}' not in pricing registry",
                detector=self.name,
            )

        # Compute average output cost of baseline models
        baseline_costs: list[float] = []
        for m in known_models:
            p = MODEL_PRICING.get(m)
            if p is not None:
                baseline_costs.append(p.output_per_1k)

        if not baseline_costs:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="No pricing data for baseline models",
                detector=self.name,
            )

        avg_baseline_cost = sum(baseline_costs) / len(baseline_costs)
        current_cost = current_pricing.output_per_1k

        if avg_baseline_cost <= 0:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="Baseline average cost is zero",
                detector=self.name,
            )

        escalation_ratio = current_cost / avg_baseline_cost

        if escalation_ratio >= 3.0:
            return DetectionResult(
                triggered=True,
                severity=Severity.MEDIUM,
                confidence=min(0.6 + (escalation_ratio - 3) * 0.05, 0.95),
                reason=(
                    f"Model '{model}' is {escalation_ratio:.1f}x more expensive "
                    f"than baseline average (${current_cost:.4f} vs "
                    f"${avg_baseline_cost:.4f} per 1k output tokens)"
                ),
                detector=self.name,
                details={
                    "model": model,
                    "current_output_cost": current_cost,
                    "baseline_avg_output_cost": round(avg_baseline_cost, 6),
                    "escalation_ratio": round(escalation_ratio, 2),
                    "known_models": known_models,
                },
            )

        return DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason="Model cost within expected range",
            detector=self.name,
        )
