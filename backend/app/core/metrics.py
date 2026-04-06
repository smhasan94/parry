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
