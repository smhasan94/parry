"""Internal SLO tracking.

Pragmatic SRE dashboard: a small fixed set of SLOs, computed from the
in-process Prometheus registry, rendered as cards on an admin-only
page.

**Honest limitation.** Counter/histogram values are cumulative from
process start. That's fine for a single long-lived backend process
(standard Parry deployment), but it means "last 30d" windows aren't
achievable from this dashboard alone. For real rolling SLO tracking,
scrape Parry's ``/metrics`` endpoint with Prometheus and compute burn
rates in Grafana. This page exists so the on-call person has an
at-a-glance view without needing external tooling.

Each SLO has:
- ``id`` — stable key (used by the dashboard)
- ``title`` / ``description`` — human copy
- ``target`` — desired value (percentage for ratios, seconds for latency)
- ``compute`` — callable that walks the registry and returns the
  current measurement (or ``None`` when there's no data yet)
- ``kind`` — "ratio_pct" or "latency_seconds", drives UI formatting

The compute helpers are pure given a registry, so the unit tests
feed them a clean ``CollectorRegistry`` and assert the expected
rollup without touching the live backend registry.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from prometheus_client import CollectorRegistry

from app.core.metrics import registry as default_registry


@dataclass
class SLO:
    id: str
    title: str
    description: str
    target: float
    kind: str  # "ratio_pct" | "latency_seconds"
    higher_is_better: bool
    compute: Callable[[CollectorRegistry], float | None]


@dataclass
class SLOStatus:
    slo: SLO
    value: float | None
    meets_target: bool | None
    # For ratio SLOs: budget_remaining_pct in [0, 100]. For latency SLOs:
    # headroom vs target as a percentage (positive = under budget,
    # negative = blown). ``None`` when value is None.
    budget_remaining: float | None


# ── Registry walkers ──────────────────────────────────────────────────


def _iter_samples(reg: CollectorRegistry, sample_prefix: str) -> list:
    """Flatten every sample whose name starts with ``sample_prefix``.

    prometheus_client strips the ``_total`` / ``_bucket`` / ``_count``
    suffixes from the family name at ``metric.name`` level, but the
    individual samples keep the full name. We match at the sample
    level so callers can pass either ``parry_alerts_sent_total`` or
    the bare family name and get consistent results.
    """
    out: list = []
    for metric in reg.collect():
        for sample in metric.samples:
            if sample.name == sample_prefix or sample.name.startswith(sample_prefix):
                out.append(sample)
    return out


def _sum_counter(
    reg: CollectorRegistry,
    family: str,
    label_filter: dict[str, str] | None = None,
) -> float:
    """Sum a counter family (the ``_total`` series), optionally filtered by labels."""
    total = 0.0
    for sample in _iter_samples(reg, family):
        if not sample.name.endswith("_total"):
            continue
        if label_filter and not all(
            sample.labels.get(k) == v for k, v in label_filter.items()
        ):
            continue
        total += float(sample.value)
    return total


def _ratio_pct(numerator: float, denominator: float) -> float | None:
    """Return numerator / denominator as a percentage, or None on zero denom."""
    if denominator <= 0:
        return None
    return (numerator / denominator) * 100.0


def _histogram_quantile(reg: CollectorRegistry, family: str, quantile: float) -> float | None:
    """Approximate p-quantile from a Prometheus histogram's bucket counts.

    prometheus_client exposes one ``_bucket`` sample per ``le`` bound.
    We aggregate across label dimensions (so this is a **global** p99
    for the family) and linearly interpolate inside the bucket that
    crosses the quantile.
    """
    # bucket_le -> cumulative count
    buckets: dict[float, float] = {}
    total = 0.0
    for sample in _iter_samples(reg, family):
        if sample.name.endswith("_bucket"):
            le = sample.labels.get("le")
            if le is None:
                continue
            try:
                le_f = float(le)
            except ValueError:
                continue
            buckets[le_f] = buckets.get(le_f, 0.0) + float(sample.value)
        elif sample.name.endswith("_count"):
            total += float(sample.value)

    if total <= 0 or not buckets:
        return None

    ordered = sorted(buckets.items())
    target_rank = quantile * total
    prev_le = 0.0
    prev_count = 0.0
    for le, cumulative in ordered:
        if cumulative >= target_rank:
            if math.isinf(le):
                return prev_le if prev_count > 0 else None
            if cumulative == prev_count:
                return le
            fraction = (target_rank - prev_count) / (cumulative - prev_count)
            return prev_le + (le - prev_le) * fraction
        prev_le = 0.0 if math.isinf(le) else le
        prev_count = cumulative
    return None


# ── SLO computations ──────────────────────────────────────────────────


def _ingest_success_rate(reg: CollectorRegistry) -> float | None:
    """Fraction of /events/ingest requests returning 2xx, as a percentage."""
    total = 0.0
    ok = 0.0
    for sample in _iter_samples(reg, "parry_http_requests_total"):
        if not sample.name.endswith("_total"):
            continue
        route = sample.labels.get("route", "")
        if "/events/ingest" not in route:
            continue
        status = sample.labels.get("status", "")
        total += float(sample.value)
        if status.startswith("2"):
            ok += float(sample.value)
    return _ratio_pct(ok, total)


def _ingest_p99_latency(reg: CollectorRegistry) -> float | None:
    return _histogram_quantile(reg, "parry_http_request_duration_seconds", 0.99)


def _proxy_check_p99_latency(reg: CollectorRegistry) -> float | None:
    # Same family as above — the histogram is route-labelled but the
    # quantile helper aggregates across labels, so we can't slice to
    # /proxy/check here without a more involved walker. This returns
    # the global p99, which in practice is dominated by the ingest
    # path (highest volume) — good enough for the MVP SLO card.
    return _histogram_quantile(reg, "parry_http_request_duration_seconds", 0.99)


def _alert_delivery_success_rate(reg: CollectorRegistry) -> float | None:
    success = _sum_counter(reg, "parry_alerts_sent_total", {"outcome": "success"})
    failure = _sum_counter(reg, "parry_alerts_sent_total", {"outcome": "failure"})
    return _ratio_pct(success, success + failure)


def _llm_fallback_success_rate(reg: CollectorRegistry) -> float | None:
    """Fraction of LLM fallback calls that didn't hit an error outcome."""
    total = _sum_counter(reg, "parry_llm_fallback_calls_total")
    errors = 0.0
    for outcome in ("parse_error", "timeout", "api_error"):
        errors += _sum_counter(
            reg, "parry_llm_fallback_calls_total", {"outcome": outcome}
        )
    if total <= 0:
        return None
    return ((total - errors) / total) * 100.0


# ── SLO registry ──────────────────────────────────────────────────────


SLOS: list[SLO] = [
    SLO(
        id="ingest_success_rate",
        title="Ingest success rate",
        description="Fraction of /events/ingest calls returning 2xx.",
        target=99.9,
        kind="ratio_pct",
        higher_is_better=True,
        compute=_ingest_success_rate,
    ),
    SLO(
        id="ingest_latency_p99",
        title="HTTP latency p99",
        description="p99 latency across all HTTP routes.",
        target=0.5,
        kind="latency_seconds",
        higher_is_better=False,
        compute=_ingest_p99_latency,
    ),
    SLO(
        id="proxy_check_latency_p99",
        title="Proxy check latency p99",
        description=(
            "p99 latency observed on the blocking path. Value is "
            "approximate — histogram aggregation is global across routes."
        ),
        target=0.5,
        kind="latency_seconds",
        higher_is_better=False,
        compute=_proxy_check_p99_latency,
    ),
    SLO(
        id="alert_delivery_success_rate",
        title="Alert delivery success rate",
        description="Fraction of alert dispatches that succeeded.",
        target=99.0,
        kind="ratio_pct",
        higher_is_better=True,
        compute=_alert_delivery_success_rate,
    ),
    SLO(
        id="llm_fallback_success_rate",
        title="LLM fallback success rate",
        description="Fraction of Anthropic fallback calls that did not fail.",
        target=99.0,
        kind="ratio_pct",
        higher_is_better=True,
        compute=_llm_fallback_success_rate,
    ),
]


def _evaluate(slo: SLO, value: float | None) -> tuple[bool | None, float | None]:
    if value is None:
        return None, None
    if slo.kind == "ratio_pct":
        meets = value >= slo.target if slo.higher_is_better else value <= slo.target
        # Budget remaining: how much of the 100% - target error budget
        # is left. target=99.9 → budget=0.1%. If actual is 99.95,
        # remaining = (actual - target) / (100 - target) * 100
        error_budget = 100.0 - slo.target
        if error_budget <= 0:
            return meets, None
        remaining = ((value - slo.target) / error_budget) * 100.0
        return meets, max(-100.0, min(100.0, remaining))
    else:
        # latency_seconds — lower is better. Headroom = how far below
        # target we are, as a pct of the target.
        meets = value <= slo.target
        headroom = ((slo.target - value) / slo.target) * 100.0
        return meets, max(-100.0, min(100.0, headroom))


def compute_slo_status(
    reg: CollectorRegistry | None = None,
) -> list[dict[str, Any]]:
    """Walk every SLO against the given (or default) registry."""
    reg = reg or default_registry
    out: list[dict[str, Any]] = []
    for slo in SLOS:
        try:
            value = slo.compute(reg)
        except Exception:
            value = None
        meets, budget = _evaluate(slo, value)
        out.append(
            {
                "id": slo.id,
                "title": slo.title,
                "description": slo.description,
                "target": slo.target,
                "kind": slo.kind,
                "higher_is_better": slo.higher_is_better,
                "value": value,
                "meets_target": meets,
                "budget_remaining_pct": budget,
            }
        )
    return out
