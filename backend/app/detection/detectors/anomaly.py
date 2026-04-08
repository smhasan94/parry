from typing import Any

from app.db.models import Severity
from app.detection.base import DetectionResult

DEFAULT_SIGMA_THRESHOLD = 3.0
MIN_BASELINE_QUALITY_FOR_ALERT = "medium"
_QUALITY_RANK = {"low": 0, "medium": 1, "high": 2}

# Per-quality multipliers applied to the configured sigma threshold.
# Low-quality baselines have noisy std dev, so we demand stronger evidence
# before flagging drift — or suppress alerting entirely when quality=low.
_QUALITY_SIGMA_MULTIPLIER = {"high": 1.0, "medium": 1.33, "low": float("inf")}


def _sigma_deviation(value: float, mean: float, std: float) -> float:
    """Return |value - mean| / std, or a mean-relative ratio when std==0.

    When std is zero (or absent), we fall back to a mean-relative measure
    (deviation / max(mean, 1)) so we still emit a meaningful number rather
    than dividing by zero.
    """
    if std and std > 0:
        return abs(value - mean) / std
    if mean:
        return abs(value - mean) / max(abs(mean), 1.0)
    return 0.0


class AnomalyDetector:
    """Detects drift from an agent's behavioral baseline.

    Compares current event metrics against the stored baseline for the agent.
    Flags significant deviations in token usage, latency, or tool call patterns.

    The sigma threshold (how many standard deviations from baseline mean count
    as drift) is configurable per-org via detector_config["anomaly"]["sigma_threshold"].
    Defaults to 3.0.

    Drift alerts are suppressed when the baseline quality is "low" — too few
    samples to trust the standard deviation.
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

        # Pull configurable sigma threshold from detector_config
        detector_cfg = (event_data.get("detector_config") or {}).get(self.name) or {}
        sigma_threshold = detector_cfg.get("sigma_threshold", DEFAULT_SIGMA_THRESHOLD)
        try:
            sigma_threshold = float(sigma_threshold)
        except (TypeError, ValueError):
            sigma_threshold = DEFAULT_SIGMA_THRESHOLD

        baseline_quality = baseline.get("quality", "high")
        quality_rank = _QUALITY_RANK.get(baseline_quality, 2)
        min_rank = _QUALITY_RANK.get(MIN_BASELINE_QUALITY_FOR_ALERT, 1)
        quality_ok = quality_rank >= min_rank

        # Effective threshold scales up for less-trusted baselines
        quality_mult = _QUALITY_SIGMA_MULTIPLIER.get(baseline_quality, 1.0)
        effective_sigma = sigma_threshold * quality_mult

        anomalies: list[str] = []
        drift: dict[str, float] = {}
        max_sigma = 0.0
        has_categorical_anomaly = False  # unknown model/tool, excessive count — binary signals

        # Token count anomaly
        token_count = event_data.get("token_count")
        baseline_avg_tokens = baseline.get("avg_token_count")
        baseline_std_tokens = baseline.get("std_token_count", 0) or 0

        if token_count and baseline_avg_tokens:
            sigma = _sigma_deviation(token_count, baseline_avg_tokens, baseline_std_tokens)
            drift["token_sigma"] = round(sigma, 2)
            max_sigma = max(max_sigma, sigma)
            if sigma >= sigma_threshold:
                anomalies.append(
                    f"Token count {token_count} is {sigma:.1f}σ from baseline "
                    f"avg {baseline_avg_tokens:.0f}"
                )

        # Latency anomaly
        latency = event_data.get("latency_ms")
        baseline_avg_latency = baseline.get("avg_latency_ms")
        baseline_std_latency = baseline.get("std_latency_ms", 0) or 0

        if latency and baseline_avg_latency:
            sigma = _sigma_deviation(latency, baseline_avg_latency, baseline_std_latency)
            drift["latency_sigma"] = round(sigma, 2)
            max_sigma = max(max_sigma, sigma)
            if sigma >= sigma_threshold:
                anomalies.append(
                    f"Latency {latency}ms is {sigma:.1f}σ from baseline "
                    f"avg {baseline_avg_latency:.0f}ms"
                )

        # Tool call count anomaly (kept as ratio rule — tool counts are small ints)
        tool_calls = event_data.get("tool_calls") or []
        baseline_avg_tools = baseline.get("avg_tool_calls")

        if baseline_avg_tools is not None:
            tool_count = len(tool_calls)
            drift["tool_count"] = float(tool_count)
            if tool_count > baseline_avg_tools * 3 and tool_count > 3:
                anomalies.append(
                    f"Tool call count {tool_count} far exceeds baseline avg "
                    f"{baseline_avg_tools:.1f}"
                )
                has_categorical_anomaly = True

        # Per-tool drift: if baseline has per-tool stats, flag tools called
        # far more often than their per-tool average.
        per_tool_baseline = baseline.get("tool_stats") or {}
        if per_tool_baseline and tool_calls:
            counts: dict[str, int] = {}
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name")
                    if isinstance(name, str):
                        counts[name] = counts.get(name, 0) + 1
            for tool_name, observed in counts.items():
                stats = per_tool_baseline.get(tool_name)
                if not isinstance(stats, dict):
                    # Previously unseen tool — flag if baseline has any tools at all
                    anomalies.append(f"Unknown tool '{tool_name}' not in baseline tool set")
                    has_categorical_anomaly = True
                    continue
                avg = float(stats.get("avg_calls", 0) or 0)
                if observed > max(avg * 3, 3):
                    anomalies.append(
                        f"Tool '{tool_name}' called {observed}x (baseline avg {avg:.1f})"
                    )
                    has_categorical_anomaly = True

        # Unseen model usage
        known_models = set(baseline.get("known_models") or [])
        model = event_data.get("model")
        if model and known_models and model not in known_models:
            anomalies.append(f"Unknown model '{model}' not in baseline models")
            has_categorical_anomaly = True

        if not anomalies:
            return DetectionResult(
                triggered=False,
                severity=Severity.LOW,
                confidence=0.8,
                reason="Event within baseline parameters",
                detector=self.name,
                details={"drift": drift, "baseline_quality": baseline_quality},
            )

        confidence = min(0.5 + len(anomalies) * 0.15, 0.95)
        severity = Severity.HIGH if len(anomalies) >= 3 else Severity.MEDIUM

        # Quality-tiered gate: low baselines never alert; medium ones require
        # the max observed drift to exceed a scaled-up effective sigma.
        if effective_sigma == float("inf"):
            meets_effective = False
        else:
            meets_effective = has_categorical_anomaly or max_sigma >= effective_sigma
        triggered = quality_ok and meets_effective
        if triggered:
            reason = f"Behavioral anomaly: {anomalies[0]}"
        elif not quality_ok:
            reason = f"Drift observed but baseline quality '{baseline_quality}' too low to alert"
        else:
            reason = (
                f"Drift observed ({max_sigma:.1f}σ) but below effective threshold "
                f"{effective_sigma:.1f}σ for quality '{baseline_quality}'"
            )

        return DetectionResult(
            triggered=triggered,
            severity=severity if triggered else Severity.LOW,
            confidence=confidence if triggered else 0.3,
            reason=reason,
            detector=self.name,
            details={
                "anomalies": anomalies,
                "count": len(anomalies),
                "drift": drift,
                "sigma_threshold": sigma_threshold,
                "effective_sigma": round(effective_sigma, 2),
                "baseline_quality": baseline_quality,
            },
        )
