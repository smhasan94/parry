"""Detection tuning sandbox — replay events with custom thresholds.

Lets users preview what would happen if they changed detector thresholds
without affecting production. Pure computation, no side effects.
"""

from __future__ import annotations

from typing import Any

from app.detection.base import BaseDetector
from app.detection.detectors.data_exfil import DataExfiltrationDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector

_DETECTORS: list[BaseDetector] = [
    PromptInjectionDetector(),
    JailbreakDetector(),
    PrivilegeEscalationDetector(),
    DataExfiltrationDetector(),
    ToolMisuseDetector(),
]


def replay_with_config(
    events: list[dict[str, Any]],
    config_overrides: dict[str, Any],
) -> dict[str, Any]:
    """Replay a list of events through detectors with custom config.

    Args:
        events: List of event dicts with prompt/response/tool_calls.
        config_overrides: Detector config overrides (thresholds, enabled flags).

    Returns:
        Summary with per-detector trigger counts and individual results.
    """
    detector_counts: dict[str, dict[str, int]] = {}
    results: list[dict[str, Any]] = []

    for event in events:
        event_data = {
            "prompt": event.get("prompt", ""),
            "response": event.get("response", ""),
            "model": event.get("model"),
            "tool_calls": event.get("tool_calls", []),
            "policy": event.get("policy", {}),
            "detector_config": config_overrides,
            "baseline": None,
        }

        event_results = []
        for d in _DETECTORS:
            # Check if detector is disabled in overrides
            det_config = config_overrides.get(d.name, {})
            if not det_config.get("enabled", True):
                continue

            r = d.detect(event_data)
            event_results.append({
                "detector": r.detector,
                "triggered": r.triggered,
                "severity": r.severity.value,
                "confidence": r.confidence,
                "reason": r.reason,
            })

            if d.name not in detector_counts:
                detector_counts[d.name] = {"triggered": 0, "total": 0}
            detector_counts[d.name]["total"] += 1
            if r.triggered:
                detector_counts[d.name]["triggered"] += 1

        results.append({
            "event_index": len(results),
            "prompt_preview": (event.get("prompt") or "")[:100],
            "detections": event_results,
            "any_triggered": any(r["triggered"] for r in event_results),
        })

    total_events = len(events)
    events_with_triggers = sum(1 for r in results if r["any_triggered"])

    return {
        "total_events": total_events,
        "events_with_triggers": events_with_triggers,
        "trigger_rate": round(events_with_triggers / max(total_events, 1) * 100, 1),
        "detector_summary": detector_counts,
        "results": results,
    }
