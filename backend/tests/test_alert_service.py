"""Tests for alert_service: should_alert, build_slack_payload."""
import uuid
from datetime import UTC, datetime

from app.db.models import Detection, Incident, IncidentStatus, Org, Severity
from app.services.alert_service import (
    SEVERITY_RANK,
    build_slack_payload,
    should_alert,
)


def _make_org(alert_config: dict | None = None) -> Org:
    return Org(
        id=uuid.uuid4(),
        name="Test Org",
        clerk_org_id=f"clerk_{uuid.uuid4().hex[:8]}",
        is_active=True,
        alert_config=alert_config,
    )


def _make_incident(
    severity: Severity = Severity.HIGH,
    detections: list[Detection] | None = None,
) -> Incident:
    incident = Incident(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        title=f"[{severity.value.upper()}] test_detector: example reason",
        severity=severity,
        status=IncidentStatus.OPEN,
        created_at=datetime.now(UTC),
    )
    incident.detections = detections or []
    return incident


def _make_detection(detector: str = "prompt_injection", confidence: float = 0.9) -> Detection:
    return Detection(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        detector=detector,
        severity=Severity.HIGH,
        confidence=confidence,
        reason=f"{detector} match",
        triggered=True,
    )


class TestShouldAlert:
    def test_no_config_returns_false(self) -> None:
        org = _make_org(alert_config=None)
        assert should_alert(org, Severity.CRITICAL) is False

    def test_empty_config_returns_false(self) -> None:
        org = _make_org(alert_config={})
        assert should_alert(org, Severity.CRITICAL) is False

    def test_no_webhook_url_returns_false(self) -> None:
        org = _make_org(alert_config={"min_severity": "low"})
        assert should_alert(org, Severity.CRITICAL) is False

    def test_default_min_severity_is_high(self) -> None:
        org = _make_org(alert_config={"slack_webhook_url": "https://hooks.slack.com/x"})
        assert should_alert(org, Severity.HIGH) is True
        assert should_alert(org, Severity.CRITICAL) is True
        assert should_alert(org, Severity.MEDIUM) is False
        assert should_alert(org, Severity.LOW) is False

    def test_explicit_min_severity_low(self) -> None:
        org = _make_org(
            alert_config={
                "slack_webhook_url": "https://hooks.slack.com/x",
                "min_severity": "low",
            }
        )
        assert should_alert(org, Severity.LOW) is True
        assert should_alert(org, Severity.CRITICAL) is True

    def test_explicit_min_severity_critical(self) -> None:
        org = _make_org(
            alert_config={
                "slack_webhook_url": "https://hooks.slack.com/x",
                "min_severity": "critical",
            }
        )
        assert should_alert(org, Severity.CRITICAL) is True
        assert should_alert(org, Severity.HIGH) is False

    def test_invalid_min_severity_falls_back_to_high(self) -> None:
        org = _make_org(
            alert_config={
                "slack_webhook_url": "https://hooks.slack.com/x",
                "min_severity": "garbage",
            }
        )
        assert should_alert(org, Severity.HIGH) is True
        assert should_alert(org, Severity.MEDIUM) is False


class TestBuildSlackPayload:
    def test_basic_payload_structure(self) -> None:
        incident = _make_incident(severity=Severity.CRITICAL)
        payload = build_slack_payload(incident)
        assert "text" in payload
        assert "critical" in payload["text"]
        assert len(payload["attachments"]) == 1
        attachment = payload["attachments"][0]
        assert attachment["color"] == "#dc2626"
        assert "fire" in attachment["title"]

    def test_includes_severity_and_status_fields(self) -> None:
        incident = _make_incident(severity=Severity.HIGH)
        payload = build_slack_payload(incident)
        fields = payload["attachments"][0]["fields"]
        field_titles = {f["title"] for f in fields}
        assert "Severity" in field_titles
        assert "Status" in field_titles

    def test_includes_top_detector_when_detections_present(self) -> None:
        detections = [
            _make_detection("anomaly", confidence=0.5),
            _make_detection("prompt_injection", confidence=0.95),
            _make_detection("jailbreak", confidence=0.7),
        ]
        incident = _make_incident(detections=detections)
        payload = build_slack_payload(incident)
        fields = payload["attachments"][0]["fields"]
        detector_field = next(f for f in fields if f["title"] == "Top Detector")
        assert "prompt_injection" in detector_field["value"]
        assert "95%" in detector_field["value"]

    def test_no_detector_field_when_empty(self) -> None:
        incident = _make_incident(detections=[])
        payload = build_slack_payload(incident)
        fields = payload["attachments"][0]["fields"]
        assert all(f["title"] != "Top Detector" for f in fields)

    def test_dashboard_url_added_as_title_link(self) -> None:
        incident = _make_incident()
        payload = build_slack_payload(incident, dashboard_url="https://parry.example.com/")
        attachment = payload["attachments"][0]
        assert attachment["title_link"] == "https://parry.example.com/incidents"

    def test_no_title_link_when_no_dashboard_url(self) -> None:
        incident = _make_incident()
        payload = build_slack_payload(incident)
        assert "title_link" not in payload["attachments"][0]


class TestSeverityRank:
    def test_ordering(self) -> None:
        assert SEVERITY_RANK[Severity.LOW] < SEVERITY_RANK[Severity.MEDIUM]
        assert SEVERITY_RANK[Severity.MEDIUM] < SEVERITY_RANK[Severity.HIGH]
        assert SEVERITY_RANK[Severity.HIGH] < SEVERITY_RANK[Severity.CRITICAL]
