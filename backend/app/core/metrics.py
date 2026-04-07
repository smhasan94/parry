"""Prometheus metrics for the Parry backend.

Exposes counters and histograms for HTTP requests, detection events, incident
creation, and alert dispatch attempts. The /metrics endpoint is unauthenticated
(scrape-only) and should be firewalled at the network layer in production.
"""
from prometheus_client import CollectorRegistry, Counter, Histogram

# Use a custom registry so tests can isolate metrics and so multiprocess workers
# can be added later via prometheus_client.multiprocess if needed.
registry = CollectorRegistry()


# ── HTTP request metrics ───────────────────────────────────────────────

http_requests_total = Counter(
    "parry_http_requests_total",
    "Total HTTP requests handled by the backend",
    labelnames=("method", "route", "status"),
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "parry_http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)


# ── Detection / business metrics ───────────────────────────────────────

events_ingested_total = Counter(
    "parry_events_ingested_total",
    "Total agent events accepted by the ingest endpoint",
    registry=registry,
)

detections_triggered_total = Counter(
    "parry_detections_triggered_total",
    "Total detections that triggered, broken down by detector and severity",
    labelnames=("detector", "severity"),
    registry=registry,
)

incidents_created_total = Counter(
    "parry_incidents_created_total",
    "Total incidents created, broken down by severity",
    labelnames=("severity",),
    registry=registry,
)

anomaly_drift_sigma = Histogram(
    "parry_anomaly_drift_sigma",
    "Max observed sigma deviation per anomaly detection, labelled by "
    "baseline quality and whether the detection triggered",
    labelnames=("quality", "triggered"),
    buckets=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0),
    registry=registry,
)

llm_fallback_calls_total = Counter(
    "parry_llm_fallback_calls_total",
    "LLM fallback Anthropic API call attempts, labelled by outcome "
    "(confirmed|cleared|parse_error|timeout|api_error|no_key)",
    labelnames=("outcome",),
    registry=registry,
)

llm_fallback_tokens_total = Counter(
    "parry_llm_fallback_tokens_total",
    "Total tokens consumed by LLM fallback Anthropic calls, labelled by "
    "direction (input|output)",
    labelnames=("direction",),
    registry=registry,
)

llm_fallback_latency_seconds = Histogram(
    "parry_llm_fallback_latency_seconds",
    "Wall-clock latency of the Anthropic API call inside llm_fallback",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0),
    registry=registry,
)

llm_fallback_cost_usd_total = Counter(
    "parry_llm_fallback_cost_usd_total",
    "Cumulative estimated USD spend on LLM fallback Anthropic calls. "
    "Computed from token counts × Claude Sonnet 4.6 published pricing.",
    registry=registry,
)


# ── Alert dispatch metrics ─────────────────────────────────────────────

alerts_sent_total = Counter(
    "parry_alerts_sent_total",
    "Alert dispatch attempts, broken down by channel and outcome",
    labelnames=("channel", "outcome"),
    registry=registry,
)


def record_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    """Record an HTTP request — called from the metrics middleware."""
    http_requests_total.labels(method=method, route=route, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, route=route).observe(duration_seconds)


def record_event_ingested() -> None:
    events_ingested_total.inc()


def record_detection_triggered(detector: str, severity: str) -> None:
    detections_triggered_total.labels(detector=detector, severity=severity).inc()


def record_incident_created(severity: str) -> None:
    incidents_created_total.labels(severity=severity).inc()


def record_alert_sent(channel: str, success: bool) -> None:
    outcome = "success" if success else "failure"
    alerts_sent_total.labels(channel=channel, outcome=outcome).inc()


def record_anomaly_drift(sigma: float, quality: str, triggered: bool) -> None:
    """Observe a drift measurement from the anomaly detector."""
    anomaly_drift_sigma.labels(
        quality=quality, triggered="true" if triggered else "false"
    ).observe(sigma)


def record_llm_fallback_call(
    outcome: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_seconds: float | None = None,
    cost_usd: float = 0.0,
) -> None:
    """Record an LLM fallback Anthropic call.

    outcome: one of confirmed, cleared, parse_error, timeout, api_error, no_key
    """
    llm_fallback_calls_total.labels(outcome=outcome).inc()
    if input_tokens:
        llm_fallback_tokens_total.labels(direction="input").inc(input_tokens)
    if output_tokens:
        llm_fallback_tokens_total.labels(direction="output").inc(output_tokens)
    if latency_seconds is not None:
        llm_fallback_latency_seconds.observe(latency_seconds)
    if cost_usd:
        llm_fallback_cost_usd_total.inc(cost_usd)
