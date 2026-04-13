"""Tests for the model pricing registry."""

from __future__ import annotations

from app.core.model_pricing import (
    MODEL_PRICING,
    PRICING_LAST_REVIEWED,
    PRICING_REVIEW_INTERVAL,
    estimate_cost,
    is_pricing_stale,
)


def test_estimate_cost_known_model() -> None:
    """gpt-4o should return a non-zero cost."""
    cost = estimate_cost("gpt-4o", input_tokens=1000, output_tokens=200)
    assert cost > 0
    # Verify math: 1000/1000 * 0.0025 + 200/1000 * 0.01 = 0.0025 + 0.002 = 0.0045
    expected = (1000 / 1000) * 0.0025 + (200 / 1000) * 0.01
    assert abs(cost - expected) < 1e-10


def test_estimate_cost_anthropic_model() -> None:
    cost = estimate_cost("claude-sonnet-4-6", input_tokens=500, output_tokens=500)
    expected = (500 / 1000) * 0.003 + (500 / 1000) * 0.015
    assert abs(cost - expected) < 1e-10


def test_estimate_cost_unknown_model() -> None:
    """Unknown models should return 0."""
    assert estimate_cost("my-custom-model-v42", 1000, 1000) == 0.0


def test_estimate_cost_none_model() -> None:
    """None model should return 0."""
    assert estimate_cost(None, 1000, 1000) == 0.0


def test_estimate_cost_zero_tokens() -> None:
    assert estimate_cost("gpt-4o", 0, 0) == 0.0


def test_all_models_have_valid_pricing() -> None:
    """Every entry in the registry must have positive costs and context window."""
    for name, p in MODEL_PRICING.items():
        assert p.input_per_1k > 0, f"{name} has non-positive input cost"
        assert p.output_per_1k > 0, f"{name} has non-positive output cost"
        assert p.context_window > 0, f"{name} has non-positive context window"
        assert p.provider in ("openai", "anthropic", "google"), f"{name} has unknown provider"


def test_is_pricing_stale_not_stale_recently() -> None:
    """The table was just reviewed — should not be stale yet."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    age = now - PRICING_LAST_REVIEWED
    if age < PRICING_REVIEW_INTERVAL:
        assert is_pricing_stale() is False
    else:
        # If the test runs >120 days after review date, stale is expected
        assert is_pricing_stale() is True
