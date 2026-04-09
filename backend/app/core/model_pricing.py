"""Model pricing registry for cost estimation.

Maps known LLM model identifiers to their per-token pricing so the
ingest pipeline can tag every event with an estimated USD cost. Unknown
models get $0 — we never block ingest over a missing price entry.

Pricing is intentionally hard-coded (not fetched from an API) because
provider pricing pages change layout constantly and a scraper failure
must never break ingest. The PRICING_LAST_REVIEWED / is_pricing_stale()
mechanism nudges maintainers to audit the table periodically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Per-model pricing metadata."""

    input_per_1k: float  # USD per 1,000 input tokens
    output_per_1k: float  # USD per 1,000 output tokens
    context_window: int  # max context length in tokens
    provider: str  # e.g. "openai", "anthropic", "google"


# Last time a human audited these numbers against provider pricing pages.
PRICING_LAST_REVIEWED = datetime(2026, 4, 1, tzinfo=UTC)
PRICING_REVIEW_INTERVAL = timedelta(days=120)


def is_pricing_stale() -> bool:
    """True when the pricing table hasn't been reviewed in PRICING_REVIEW_INTERVAL."""
    return datetime.now(UTC) - PRICING_LAST_REVIEWED > PRICING_REVIEW_INTERVAL


# ── Pricing table ──────────────────────────────────────────────────

MODEL_PRICING: dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o": ModelPricing(
        input_per_1k=0.0025, output_per_1k=0.0100, context_window=128_000, provider="openai"
    ),
    "gpt-4o-mini": ModelPricing(
        input_per_1k=0.00015, output_per_1k=0.00060, context_window=128_000, provider="openai"
    ),
    "gpt-4-turbo": ModelPricing(
        input_per_1k=0.0100, output_per_1k=0.0300, context_window=128_000, provider="openai"
    ),
    "gpt-4": ModelPricing(
        input_per_1k=0.0300, output_per_1k=0.0600, context_window=8_192, provider="openai"
    ),
    "gpt-3.5-turbo": ModelPricing(
        input_per_1k=0.0005, output_per_1k=0.0015, context_window=16_385, provider="openai"
    ),
    "o1": ModelPricing(
        input_per_1k=0.0150, output_per_1k=0.0600, context_window=200_000, provider="openai"
    ),
    "o1-mini": ModelPricing(
        input_per_1k=0.0030, output_per_1k=0.0120, context_window=128_000, provider="openai"
    ),
    # Anthropic
    "claude-opus-4-6": ModelPricing(
        input_per_1k=0.0150, output_per_1k=0.0750, context_window=200_000, provider="anthropic"
    ),
    "claude-sonnet-4-6": ModelPricing(
        input_per_1k=0.0030, output_per_1k=0.0150, context_window=200_000, provider="anthropic"
    ),
    "claude-haiku-4-5": ModelPricing(
        input_per_1k=0.0008, output_per_1k=0.0040, context_window=200_000, provider="anthropic"
    ),
    "claude-3-5-sonnet": ModelPricing(
        input_per_1k=0.0030, output_per_1k=0.0150, context_window=200_000, provider="anthropic"
    ),
    "claude-3-5-haiku": ModelPricing(
        input_per_1k=0.0008, output_per_1k=0.0040, context_window=200_000, provider="anthropic"
    ),
    # Google
    "gemini-1.5-pro": ModelPricing(
        input_per_1k=0.00125, output_per_1k=0.0050, context_window=2_000_000, provider="google"
    ),
    "gemini-1.5-flash": ModelPricing(
        input_per_1k=0.000075, output_per_1k=0.00030, context_window=1_000_000, provider="google"
    ),
}


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a model call. Returns 0.0 for unknown models."""
    if not model:
        return 0.0
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return 0.0
    return (input_tokens / 1000.0) * pricing.input_per_1k + (
        output_tokens / 1000.0
    ) * pricing.output_per_1k
