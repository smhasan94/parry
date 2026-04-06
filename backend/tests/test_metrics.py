"""Tests for app.core.metrics — recorders and the /metrics endpoint."""
from fastapi.testclient import TestClient

from app.core.metrics import (
    alerts_sent_total,
    detections_triggered_total,
    events_ingested_total,
    http_requests_total,
    incidents_created_total,
    record_alert_sent,
    record_detection_triggered,
    record_event_ingested,
    record_incident_created,
    record_request,
)


def _counter_value(counter, **labels) -> float:
    """Read the current value of a labeled counter."""
    return counter.labels(**labels)._value.get()


class TestRecordRequest:
    def test_increments_total(self) -> None:
        before = _counter_value(
            http_requests_total, method="GET", route="/api/v1/agents", status="200"
        )
        record_request("GET", "/api/v1/agents", 200, 0.05)
        after = _counter_value(
            http_requests_total, method="GET", route="/api/v1/agents", status="200"
        )
        assert after == before + 1

    def test_separate_labels_tracked_independently(self) -> None:
        record_request("POST", "/api/v1/events/ingest", 202, 0.01)
        record_request("POST", "/api/v1/events/ingest", 401, 0.01)
        ok = _counter_value(
            http_requests_total,
            method="POST",
            route="/api/v1/events/ingest",
            status="202",
        )
        unauth = _counter_value(
            http_requests_total,
            method="POST",
            route="/api/v1/events/ingest",
            status="401",
        )
        assert ok >= 1
        assert unauth >= 1


class TestRecordEventIngested:
    def test_increments(self) -> None:
        before = events_ingested_total._value.get()
        record_event_ingested()
        record_event_ingested()
        assert events_ingested_total._value.get() == before + 2


class TestRecordDetectionTriggered:
    def test_labels_by_detector_and_severity(self) -> None:
        before = _counter_value(
            detections_triggered_total, detector="prompt_injection", severity="high"
        )
        record_detection_triggered("prompt_injection", "high")
        after = _counter_value(
            detections_triggered_total, detector="prompt_injection", severity="high"
        )
        assert after == before + 1


class TestRecordIncidentCreated:
    def test_labels_by_severity(self) -> None:
        before = _counter_value(incidents_created_total, severity="critical")
        record_incident_created("critical")
        record_incident_created("critical")
        after = _counter_value(incidents_created_total, severity="critical")
        assert after == before + 2


class TestRecordAlertSent:
    def test_success_labeled_correctly(self) -> None:
        before = _counter_value(alerts_sent_total, channel="slack", outcome="success")
        record_alert_sent("slack", success=True)
        after = _counter_value(alerts_sent_total, channel="slack", outcome="success")
        assert after == before + 1

    def test_failure_labeled_correctly(self) -> None:
        before = _counter_value(alerts_sent_total, channel="email", outcome="failure")
        record_alert_sent("email", success=False)
        after = _counter_value(alerts_sent_total, channel="email", outcome="failure")
        assert after == before + 1

    def test_separate_channels_tracked_independently(self) -> None:
        slack_before = _counter_value(alerts_sent_total, channel="slack", outcome="success")
        email_before = _counter_value(alerts_sent_total, channel="email", outcome="success")
        record_alert_sent("slack", success=True)
        slack_after = _counter_value(alerts_sent_total, channel="slack", outcome="success")
        email_after = _counter_value(alerts_sent_total, channel="email", outcome="success")
        assert slack_after == slack_before + 1
        assert email_after == email_before  # email not touched


class TestMetricsEndpoint:
    def test_returns_200_with_prometheus_content_type(self) -> None:
        from app.main import app

        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_exposes_parry_metrics(self) -> None:
        from app.main import app

        client = TestClient(app)
        resp = client.get("/metrics")
        body = resp.text
        # Each registered metric should appear in the output
        assert "parry_http_requests_total" in body
        assert "parry_http_request_duration_seconds" in body
        assert "parry_events_ingested_total" in body
        assert "parry_detections_triggered_total" in body
        assert "parry_incidents_created_total" in body
        assert "parry_alerts_sent_total" in body

    def test_metrics_endpoint_does_not_record_itself(self) -> None:
        """Hitting /metrics should not increment HTTP request counters."""
        from app.main import app

        client = TestClient(app)
        before = _counter_value(
            http_requests_total, method="GET", route="/metrics", status="200"
        )
        client.get("/metrics")
        client.get("/metrics")
        after = _counter_value(
            http_requests_total, method="GET", route="/metrics", status="200"
        )
        assert after == before  # middleware skips /metrics
