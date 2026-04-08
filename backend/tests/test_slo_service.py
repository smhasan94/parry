"""Unit tests for slo_service.

Uses clean, disposable prometheus_client registries so we never touch
the live backend registry and so test ordering is irrelevant.
"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Histogram

from app.services import slo_service

# ── Helpers ──────────────────────────────────────────────────────────


def _make_request_counter(reg: CollectorRegistry) -> Counter:
    return Counter(
        "parry_http_requests_total",
        "test",
        labelnames=("method", "route", "status"),
        registry=reg,
    )


def _make_histogram(reg: CollectorRegistry) -> Histogram:
    return Histogram(
        "parry_http_request_duration_seconds",
        "test",
        labelnames=("method", "route"),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=reg,
    )


def _make_alert_counter(reg: CollectorRegistry) -> Counter:
    return Counter(
        "parry_alerts_sent_total",
        "test",
        labelnames=("channel", "outcome"),
        registry=reg,
    )


def _make_llm_counter(reg: CollectorRegistry) -> Counter:
    return Counter(
        "parry_llm_fallback_calls_total",
        "test",
        labelnames=("outcome",),
        registry=reg,
    )


# ── _ratio_pct + _sum_counter ────────────────────────────────────────


def test_ratio_pct_empty() -> None:
    assert slo_service._ratio_pct(0, 0) is None
    assert slo_service._ratio_pct(5, 0) is None


def test_ratio_pct_happy_path() -> None:
    assert slo_service._ratio_pct(99, 100) == 99.0
    assert slo_service._ratio_pct(1, 4) == 25.0


def test_sum_counter_with_and_without_filter() -> None:
    reg = CollectorRegistry()
    c = _make_alert_counter(reg)
    c.labels(channel="slack", outcome="success").inc(10)
    c.labels(channel="slack", outcome="failure").inc(2)
    c.labels(channel="email", outcome="success").inc(5)

    assert slo_service._sum_counter(reg, "parry_alerts_sent_total") == 17
    assert (
        slo_service._sum_counter(
            reg, "parry_alerts_sent_total", {"outcome": "success"}
        )
        == 15
    )
    assert (
        slo_service._sum_counter(
            reg, "parry_alerts_sent_total", {"channel": "email"}
        )
        == 5
    )


# ── Ingest success rate ──────────────────────────────────────────────


def test_ingest_success_rate_none_when_no_traffic() -> None:
    reg = CollectorRegistry()
    _make_request_counter(reg)
    assert slo_service._ingest_success_rate(reg) is None


def test_ingest_success_rate_ignores_other_routes() -> None:
    reg = CollectorRegistry()
    c = _make_request_counter(reg)
    # Non-ingest traffic shouldn't dilute the ingest SLO.
    c.labels(method="GET", route="/api/v1/agents", status="200").inc(50)
    c.labels(method="POST", route="/api/v1/events/ingest", status="200").inc(99)
    c.labels(method="POST", route="/api/v1/events/ingest", status="500").inc(1)
    rate = slo_service._ingest_success_rate(reg)
    assert rate == 99.0


def test_ingest_success_rate_counts_all_2xx() -> None:
    reg = CollectorRegistry()
    c = _make_request_counter(reg)
    c.labels(method="POST", route="/api/v1/events/ingest", status="200").inc(3)
    c.labels(method="POST", route="/api/v1/events/ingest", status="202").inc(7)
    c.labels(method="POST", route="/api/v1/events/ingest", status="500").inc(0)
    assert slo_service._ingest_success_rate(reg) == 100.0


# ── Histogram p99 ────────────────────────────────────────────────────


def test_histogram_quantile_none_when_empty() -> None:
    reg = CollectorRegistry()
    _make_histogram(reg)
    assert slo_service._ingest_p99_latency(reg) is None


def test_histogram_quantile_reasonable_p99() -> None:
    reg = CollectorRegistry()
    h = _make_histogram(reg)
    # 99 fast observations + 1 slow one — p99 should land in the
    # 1.0-2.5 bucket band, not the fast tail.
    for _ in range(99):
        h.labels(method="POST", route="/api/v1/events/ingest").observe(0.02)
    h.labels(method="POST", route="/api/v1/events/ingest").observe(2.0)
    p99 = slo_service._ingest_p99_latency(reg)
    assert p99 is not None
    assert 0.025 <= p99 <= 2.5  # bucket boundaries we care about


# ── Alert delivery ───────────────────────────────────────────────────


def test_alert_delivery_success_rate() -> None:
    reg = CollectorRegistry()
    c = _make_alert_counter(reg)
    c.labels(channel="slack", outcome="success").inc(198)
    c.labels(channel="slack", outcome="failure").inc(2)
    rate = slo_service._alert_delivery_success_rate(reg)
    assert rate == pytest.approx(99.0)


def test_alert_delivery_none_when_no_alerts() -> None:
    reg = CollectorRegistry()
    _make_alert_counter(reg)
    assert slo_service._alert_delivery_success_rate(reg) is None


# ── LLM fallback ─────────────────────────────────────────────────────


def test_llm_fallback_success_rate() -> None:
    reg = CollectorRegistry()
    c = _make_llm_counter(reg)
    c.labels(outcome="confirmed").inc(95)
    c.labels(outcome="cleared").inc(3)
    c.labels(outcome="api_error").inc(1)
    c.labels(outcome="timeout").inc(1)
    rate = slo_service._llm_fallback_success_rate(reg)
    assert rate == pytest.approx(98.0)


# ── _evaluate ────────────────────────────────────────────────────────


def test_evaluate_ratio_meeting_target() -> None:
    slo = slo_service.SLOS[0]  # ingest_success_rate, target 99.9
    meets, budget = slo_service._evaluate(slo, 99.95)
    assert meets is True
    assert budget is not None
    assert budget > 0


def test_evaluate_ratio_breaching_target() -> None:
    slo = slo_service.SLOS[0]
    meets, budget = slo_service._evaluate(slo, 99.0)
    assert meets is False
    assert budget is not None
    assert budget < 0


def test_evaluate_latency_meeting_target() -> None:
    slo = slo_service.SLOS[1]  # latency p99, target 0.5s, lower is better
    meets, headroom = slo_service._evaluate(slo, 0.1)
    assert meets is True
    assert headroom is not None
    assert headroom > 0


def test_evaluate_latency_breaching_target() -> None:
    slo = slo_service.SLOS[1]
    meets, headroom = slo_service._evaluate(slo, 1.0)
    assert meets is False
    assert headroom is not None
    assert headroom < 0


def test_evaluate_none_value_returns_none() -> None:
    slo = slo_service.SLOS[0]
    meets, budget = slo_service._evaluate(slo, None)
    assert meets is None
    assert budget is None


# ── compute_slo_status end-to-end ────────────────────────────────────


def test_compute_slo_status_returns_all_defined_slos() -> None:
    reg = CollectorRegistry()  # empty registry — every compute should return None
    statuses = slo_service.compute_slo_status(reg)
    assert len(statuses) == len(slo_service.SLOS)
    assert {s["id"] for s in statuses} == {slo.id for slo in slo_service.SLOS}
    for s in statuses:
        assert s["value"] is None
        assert s["meets_target"] is None
        assert s["budget_remaining_pct"] is None


def test_compute_slo_status_survives_compute_error() -> None:
    # Patch one SLO to raise — the rest should still evaluate.
    reg = CollectorRegistry()
    _make_request_counter(reg)
    original = slo_service.SLOS[0].compute
    slo_service.SLOS[0].compute = lambda _r: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        statuses = slo_service.compute_slo_status(reg)
    finally:
        slo_service.SLOS[0].compute = original
    assert statuses[0]["value"] is None
    assert statuses[0]["meets_target"] is None
