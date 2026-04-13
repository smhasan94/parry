"""Tests for the three cost exploitation detectors."""

from __future__ import annotations

from app.detection.detectors.cost_explosion import (
    CostExploitLoopDetector,
    CostExploitModelEscalationDetector,
    CostExploitVerbosityDetector,
)

# ── CostExploitLoopDetector ────────────────────────────────────


LOOP_DETECTOR = CostExploitLoopDetector()


def _loop_event(
    history_size: int = 20,
    identical_ratio: float = 1.0,
    tool_names: list[str] | None = None,
) -> dict:
    """Build an event_data dict for loop detection tests."""
    if tool_names is None:
        tool_names = ["search"]
    tc = [{"name": n} for n in tool_names]
    different_tc = [{"name": "different_tool"}]
    n_identical = int(history_size * identical_ratio)
    history = [{"tool_calls": tc} for _ in range(n_identical)] + [
        {"tool_calls": different_tc} for _ in range(history_size - n_identical)
    ]
    return {
        "tool_calls": tc,
        "session_history": history,
    }


def test_loop_triggered_high_ratio() -> None:
    event = _loop_event(history_size=20, identical_ratio=0.8)
    result = LOOP_DETECTOR.detect(event)
    assert result.triggered is True
    assert result.severity.value == "medium"


def test_loop_not_triggered_low_history() -> None:
    event = _loop_event(history_size=5)
    result = LOOP_DETECTOR.detect(event)
    assert result.triggered is False


def test_loop_not_triggered_diverse_calls() -> None:
    """When calls are diverse, no loop should be detected."""
    history = [{"tool_calls": [{"name": f"tool_{i}"}]} for i in range(20)]
    event = {
        "tool_calls": [{"name": "unique_tool"}],
        "session_history": history,
    }
    result = LOOP_DETECTOR.detect(event)
    assert result.triggered is False


def test_loop_not_triggered_no_tool_calls() -> None:
    event = {
        "session_history": [{"text": "hello"} for _ in range(15)],
        "tool_calls": [],
    }
    result = LOOP_DETECTOR.detect(event)
    assert result.triggered is False


def test_loop_not_triggered_no_history() -> None:
    result = LOOP_DETECTOR.detect({"tool_calls": [{"name": "x"}]})
    assert result.triggered is False


# ── CostExploitVerbosityDetector ───────────────────────────────


VERBOSITY_DETECTOR = CostExploitVerbosityDetector()


def test_verbosity_triggered() -> None:
    event = {
        "token_count": 50_000,
        "baseline": {"avg_token_count": 500},
    }
    result = VERBOSITY_DETECTOR.detect(event)
    assert result.triggered is True
    assert result.severity.value == "medium"


def test_verbosity_not_triggered_normal() -> None:
    event = {
        "token_count": 600,
        "baseline": {"avg_token_count": 500},
    }
    result = VERBOSITY_DETECTOR.detect(event)
    assert result.triggered is False


def test_verbosity_not_triggered_no_baseline() -> None:
    event = {"token_count": 50_000}
    result = VERBOSITY_DETECTOR.detect(event)
    assert result.triggered is False


def test_verbosity_exactly_10x() -> None:
    """10x should trigger."""
    event = {
        "token_count": 5000,
        "baseline": {"avg_token_count": 500},
    }
    result = VERBOSITY_DETECTOR.detect(event)
    assert result.triggered is True


def test_verbosity_just_under_10x() -> None:
    event = {
        "token_count": 4999,
        "baseline": {"avg_token_count": 500},
    }
    result = VERBOSITY_DETECTOR.detect(event)
    assert result.triggered is False


# ── CostExploitModelEscalationDetector ─────────────────────────


ESCALATION_DETECTOR = CostExploitModelEscalationDetector()


def test_escalation_triggered() -> None:
    """gpt-4 (output $0.06/1k) vs baseline of gpt-3.5-turbo ($0.0015/1k) = 40x."""
    event = {
        "model": "gpt-4",
        "baseline": {"known_models": ["gpt-3.5-turbo"]},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is True
    assert result.severity.value == "medium"


def test_escalation_not_triggered_same_model() -> None:
    event = {
        "model": "gpt-4o",
        "baseline": {"known_models": ["gpt-4o"]},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is False


def test_escalation_not_triggered_no_baseline() -> None:
    event = {"model": "gpt-4"}
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is False


def test_escalation_not_triggered_unknown_model() -> None:
    event = {
        "model": "unknown-model-xyz",
        "baseline": {"known_models": ["gpt-4o"]},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is False


def test_escalation_not_triggered_no_known_models() -> None:
    event = {
        "model": "gpt-4",
        "baseline": {"known_models": []},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is False


def test_escalation_moderate_upgrade() -> None:
    """gpt-4o ($0.01/1k output) vs gpt-4o-mini ($0.0006/1k) = ~16.7x — should trigger."""
    event = {
        "model": "gpt-4o",
        "baseline": {"known_models": ["gpt-4o-mini"]},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is True


def test_escalation_small_upgrade_no_trigger() -> None:
    """claude-sonnet-4-6 vs claude-3-5-sonnet — same price, no escalation."""
    event = {
        "model": "claude-sonnet-4-6",
        "baseline": {"known_models": ["claude-3-5-sonnet"]},
    }
    result = ESCALATION_DETECTOR.detect(event)
    assert result.triggered is False
