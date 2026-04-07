"""Tests for the JSON metrics-query API (dashboard-facing chart data).

These call the endpoint handler directly to avoid the full middleware
stack (rate limiter, Redis, auth) — the handler is a pure function over
the in-process registry, so a unit-level call covers the logic we care
about without needing Redis/DB."""
import pytest

from app.api.v1.metrics_query import get_anomaly_drift_histogram
from app.core.metrics import record_anomaly_drift


@pytest.mark.asyncio
async def test_anomaly_drift_histogram_shape():
    """Observe a few drift values, call the handler, verify the response
    groups samples by (quality, triggered) with sorted cumulative buckets."""
    record_anomaly_drift(1.2, "high", triggered=False)
    record_anomaly_drift(4.8, "high", triggered=True)
    record_anomaly_drift(2.5, "medium", triggered=False)

    resp = await get_anomaly_drift_histogram(_org=None)  # auth dep ignored

    assert resp.note
    assert len(resp.series) >= 2

    high_triggered = next(
        (s for s in resp.series if s.quality == "high" and s.triggered),
        None,
    )
    assert high_triggered is not None
    assert high_triggered.total >= 1
    assert high_triggered.sum >= 4.8

    les = [b.le for b in high_triggered.buckets]
    assert les == sorted(les)
    # Last bucket (+Inf) count equals total since histograms are cumulative
    assert high_triggered.buckets[-1].count == high_triggered.total
    assert high_triggered.buckets[-1].le == float("inf")


@pytest.mark.asyncio
async def test_empty_histogram_still_returns_valid_shape():
    """Labels that were never observed simply don't appear; the response
    stays a valid DriftHistogramResponse."""
    resp = await get_anomaly_drift_histogram(_org=None)
    # series may be empty or populated depending on test order; the contract
    # is just that it's a list and has the note
    assert isinstance(resp.series, list)
    assert resp.note
