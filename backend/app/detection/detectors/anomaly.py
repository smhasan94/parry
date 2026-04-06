from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult


class AnomalyDetector:
    """Detects drift from an agent's behavioral baseline.

    Compares current event metrics against the stored baseline for the agent.
    Flags significant deviations in token usage, latency, or tool call patterns.
    """

    name = "anomaly"

    def detect(self, event_data: dict[str, Any]) -> DetectionResult:
        baseline = event_data.get("baseline") or {}

        if not baseline:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.0,
                reason="No baseline established for agent",
                detector=self.name,
            )

        anomalies: list[str] = []

        # Token count anomaly
        token_count = event_data.get("token_count")
        baseline_avg_tokens = baseline.get("avg_token_count")
        baseline_std_tokens = baseline.get("std_token_count", 0)

        if token_count and baseline_avg_tokens:
            deviation = abs(token_count - baseline_avg_tokens)
            threshold = max(baseline_std_tokens * 3, baseline_avg_tokens * 0.5)
            if deviation > threshold:
                anomalies.append(
                    f"Token count {token_count} deviates from baseline "
                    f"avg {baseline_avg_tokens:.0f}"
                )

        # Latency anomaly
        latency = event_data.get("latency_ms")
        baseline_avg_latency = baseline.get("avg_latency_ms")
        baseline_std_latency = baseline.get("std_latency_ms", 0)

        if latency and baseline_avg_latency:
            deviation = abs(latency - baseline_avg_latency)
            threshold = max(baseline_std_latency * 3, baseline_avg_latency * 0.5)
            if deviation > threshold:
                anomalies.append(
                    f"Latency {latency}ms deviates from baseline avg {baseline_avg_latency:.0f}ms"
                )

        # Tool call count anomaly
        tool_calls = event_data.get("tool_calls") or []
        baseline_avg_tools = baseline.get("avg_tool_calls")

        if baseline_avg_tools is not None:
            tool_count = len(tool_calls)
            if tool_count > baseline_avg_tools * 3 and tool_count > 3:
                anomalies.append(
                    f"Tool call count {tool_count} far exceeds baseline avg "
                    f"{baseline_avg_tools:.1f}"
                )

        # Unseen model usage
        known_models = set(baseline.get("known_models") or [])
        model = event_data.get("model")
        if model and known_models and model not in known_models:
            anomalies.append(f"Unknown model '{model}' not in baseline models")

        if not anomalies:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.8,
                reason="Event within baseline parameters",
                detector=self.name,
            )

        confidence = min(0.5 + len(anomalies) * 0.15, 0.95)
        severity = Severity.HIGH if len(anomalies) >= 3 else Severity.MEDIUM

        return DetectionResult(
            triggered=True,
            severity=severity,
            confidence=confidence,
            reason=f"Behavioral anomaly: {anomalies[0]}",
            detector=self.name,
            details={"anomalies": anomalies, "count": len(anomalies)},
        )
