"""JSON projections of in-process Prometheus metrics for the dashboard.

These endpoints read the custom registry directly — no Prometheus scrape
required. Intentionally scoped narrow: one endpoint per chart the dashboard
needs. If we outgrow in-process reads (multi-worker, horizontal scaling),
these can be replaced with real PromQL queries without breaking the
dashboard contract.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_org
from app.core.metrics import anomaly_drift_sigma
from app.db.models import Org
from app.schemas.base import ParrySchema

router = APIRouter()


class DriftBucket(ParrySchema):
    """One bucket in the anomaly drift histogram.

    `le` is Prometheus' "less than or equal" upper bound; `None` means the
    unbounded +Inf tail bucket. `count` is the CUMULATIVE count at or
    below that bound — i.e. `bucket[3].count` is the number of observations
    ≤ `bucket[3].le`. The dashboard converts these to per-bucket counts.

    +Inf is serialized as null rather than the Python `float("inf")` value
    because `Infinity` is not valid JSON and trips strict parsers.
    """

    le: float | None
    count: float


class DriftSeries(ParrySchema):
    quality: str
    triggered: bool
    total: float
    sum: float
    buckets: list[DriftBucket]


class DriftHistogramResponse(ParrySchema):
    series: list[DriftSeries]
    note: str = (
        "In-process counters from a single backend worker. Under horizontal "
        "scaling this is a lower bound, not a cluster total."
    )


@router.get("/anomaly-drift", response_model=DriftHistogramResponse)
async def get_anomaly_drift_histogram(
    _org: Org = Depends(get_current_org),
) -> DriftHistogramResponse:
    """Return the parry_anomaly_drift_sigma histogram grouped by label set.

    Note: metric is not label-partitioned by org today, so this returns a
    process-wide view. That's deliberate — the chart is a tuning aid for
    admins setting detector thresholds, not a per-tenant analytics surface.
    """
    # Bundle samples by (quality, triggered) label pair
    grouped: dict[tuple[str, str], DriftSeries] = {}

    for family in anomaly_drift_sigma.collect():
        for sample in family.samples:
            key = (
                sample.labels.get("quality", "unknown"),
                sample.labels.get("triggered", "false"),
            )
            series = grouped.get(key)
            if series is None:
                series = DriftSeries(
                    quality=key[0],
                    triggered=key[1] == "true",
                    total=0.0,
                    sum=0.0,
                    buckets=[],
                )
                grouped[key] = series

            if sample.name.endswith("_bucket"):
                le_raw = sample.labels.get("le", "+Inf")
                le: float | None = None if le_raw in ("+Inf", "inf") else float(le_raw)
                series.buckets.append(DriftBucket(le=le, count=sample.value))
            elif sample.name.endswith("_count"):
                series.total = sample.value
            elif sample.name.endswith("_sum"):
                series.sum = sample.value

    # Sort buckets ascending by upper bound so consumers can walk cumulative
    # counts in order. `None` (+Inf) sorts last.
    for series in grouped.values():
        series.buckets.sort(key=lambda b: (b.le is None, b.le if b.le is not None else 0.0))

    return DriftHistogramResponse(series=list(grouped.values()))
