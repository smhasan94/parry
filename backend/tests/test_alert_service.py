"""Tests for alert_service: should_alert, build_slack_payload, email helpers."""
import uuid
from datetime import UTC, datetime

from app.db.models import Detection, Incident, IncidentStatus, Org, Severity
from app.services.alert_service import (
    SEVERITY_RANK,
    build_email_html,
    build_email_subject,
    build_opsgenie_payload,
    build_pagerduty_payload,
    build_slack_payload,
    build_webhook_payload,
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

    def test_no_channel_returns_false(self) -> None:
        org = _make_org(alert_config={"min_severity": "low"})
        assert should_alert(org, Severity.CRITICAL) is False

    def test_emails_only_is_a_valid_channel(self) -> None:
        org = _make_org(
            alert_config={
                "alert_emails": ["ops@example.com"],
                "min_severity": "high",
            }
        )
        assert should_alert(org, Severity.HIGH) is True
        assert should_alert(org, Severity.MEDIUM) is False

    def test_webhook_only_is_a_valid_channel(self) -> None:
        org = _make_org(
            alert_config={
                "webhook_url": "https://api.pagerduty.com/integration/abc",
                "min_severity": "critical",
            }
        )
        assert should_alert(org, Severity.CRITICAL) is True
        assert should_alert(org, Severity.HIGH) is False

    def test_both_channels_configured(self) -> None:
        org = _make_org(
            alert_config={
                "slack_webhook_url": "https://hooks.slack.com/x",
                "alert_emails": ["ops@example.com"],
                "min_severity": "low",
            }
        )
        assert should_alert(org, Severity.LOW) is True

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


class TestBuildEmailSubject:
    def test_includes_severity_and_title(self) -> None:
        incident = _make_incident(severity=Severity.CRITICAL)
        subject = build_email_subject(incident)
        assert "CRITICAL" in subject
        assert "Parry" in subject
        assert incident.title in subject


class TestBuildEmailHtml:
    def test_contains_severity_label(self) -> None:
        incident = _make_incident(severity=Severity.HIGH)
        html = build_email_html(incident)
        assert "HIGH severity" in html
        assert incident.title in html

    def test_includes_detector_table_when_detections_present(self) -> None:
        detections = [
            _make_detection("anomaly", confidence=0.5),
            _make_detection("prompt_injection", confidence=0.95),
        ]
        incident = _make_incident(detections=detections)
        html = build_email_html(incident)
        assert "prompt_injection" in html
        assert "anomaly" in html
        assert "95%" in html

    def test_no_detector_table_when_empty(self) -> None:
        incident = _make_incident(detections=[])
        html = build_email_html(incident)
        assert "<table" not in html

    def test_dashboard_link_added_when_url_provided(self) -> None:
        incident = _make_incident()
        html = build_email_html(incident, dashboard_url="https://parry.example.com")
        assert "https://parry.example.com/incidents" in html
        assert "View in Dashboard" in html

    def test_no_link_when_no_dashboard_url(self) -> None:
        incident = _make_incident()
        html = build_email_html(incident)
        assert "View in Dashboard" not in html

    def test_critical_uses_red_color(self) -> None:
        incident = _make_incident(severity=Severity.CRITICAL)
        html = build_email_html(incident)
        assert "#dc2626" in html


class TestBuildWebhookPayload:
    def test_payload_shape(self) -> None:
        incident = _make_incident(severity=Severity.CRITICAL)
        payload = build_webhook_payload(incident)
        assert payload["schema_version"] == "1.0"
        assert payload["event"] == "incident.created"
        assert "incident" in payload

    def test_incident_fields(self) -> None:
        incident = _make_incident(severity=Severity.HIGH)
        payload = build_webhook_payload(incident)
        inc = payload["incident"]
        assert inc["id"] == str(incident.id)
        assert inc["title"] == incident.title
        assert inc["severity"] == "high"
        assert inc["status"] == "open"
        assert inc["agent_id"] == str(incident.agent_id)
        assert "created_at" in inc

    def test_includes_detections_sorted_by_confidence_desc(self) -> None:
        detections = [
            _make_detection("anomaly", confidence=0.5),
            _make_detection("prompt_injection", confidence=0.95),
            _make_detection("jailbreak", confidence=0.7),
        ]
        incident = _make_incident(detections=detections)
        payload = build_webhook_payload(incident)
        names = [d["detector"] for d in payload["incident"]["detections"]]
        assert names == ["prompt_injection", "jailbreak", "anomaly"]

    def test_no_detections_returns_empty_list(self) -> None:
        incident = _make_incident(detections=[])
        payload = build_webhook_payload(incident)
        assert payload["incident"]["detections"] == []

    def test_dashboard_url_added_when_provided(self) -> None:
        incident = _make_incident()
        payload = build_webhook_payload(incident, dashboard_url="https://parry.example.com/")
        assert payload["incident"]["dashboard_url"] == "https://parry.example.com/incidents"

    def test_no_dashboard_url_omits_field(self) -> None:
        incident = _make_incident()
        payload = build_webhook_payload(incident)
        assert "dashboard_url" not in payload["incident"]

    def test_payload_is_json_serializable(self) -> None:
        """Generic webhook receivers expect plain JSON — no UUIDs or datetimes."""
        import json

        incident = _make_incident()
        payload = build_webhook_payload(incident, dashboard_url="https://x.com")
        # Must not raise
        json_str = json.dumps(payload)
        assert "schema_version" in json_str


class TestBuildPagerDutyPayload:
    def test_severity_mapping(self) -> None:
        for sev, expected in [
            (Severity.CRITICAL, "critical"),
            (Severity.HIGH, "error"),
            (Severity.MEDIUM, "warning"),
            (Severity.LOW, "info"),
        ]:
            payload = build_pagerduty_payload(_make_incident(severity=sev), "rk_x")
            assert payload["payload"]["severity"] == expected

    def test_dedup_key_uses_incident_id(self) -> None:
        incident = _make_incident()
        payload = build_pagerduty_payload(incident, "rk_x")
        assert payload["dedup_key"] == f"parry-incident-{incident.id}"
        assert payload["event_action"] == "trigger"
        assert payload["routing_key"] == "rk_x"
        assert payload["payload"]["source"] == "Parry AI Security"

    def test_custom_details_include_ids(self) -> None:
        incident = _make_incident(detections=[_make_detection(confidence=0.88)])
        payload = build_pagerduty_payload(
            incident, "rk_x", dashboard_url="https://parry.example.com/"
        )
        details = payload["payload"]["custom_details"]
        assert details["incident_id"] == str(incident.id)
        assert details["agent_id"] == str(incident.agent_id)
        assert details["dashboard_url"].endswith("/incidents")
        assert details["top_detector"] == "prompt_injection"


class TestBuildOpsgeniePayload:
    def test_priority_mapping(self) -> None:
        for sev, expected in [
            (Severity.CRITICAL, "P1"),
            (Severity.HIGH, "P2"),
            (Severity.MEDIUM, "P3"),
            (Severity.LOW, "P5"),
        ]:
            payload = build_opsgenie_payload(_make_incident(severity=sev))
            assert payload["priority"] == expected

    def test_alias_is_deterministic(self) -> None:
        incident = _make_incident()
        payload = build_opsgenie_payload(incident)
        assert payload["alias"] == f"parry-{incident.id}"
        assert "parry" in payload["tags"]
        assert incident.severity.value in payload["tags"]

    def test_details_include_dashboard_url(self) -> None:
        incident = _make_incident()
        payload = build_opsgenie_payload(
            incident, dashboard_url="https://parry.example.com/"
        )
        assert payload["details"]["dashboard_url"].endswith("/incidents")


class TestShouldAlertPagerDutyOpsgenie:
    def test_pagerduty_key_counts_as_channel(self) -> None:
        org = _make_org(
            alert_config={"pagerduty_routing_key": "rk_x", "min_severity": "high"}
        )
        assert should_alert(org, Severity.HIGH)
        assert not should_alert(org, Severity.MEDIUM)

    def test_opsgenie_key_counts_as_channel(self) -> None:
        org = _make_org(
            alert_config={"opsgenie_api_key": "k", "min_severity": "critical"}
        )
        assert should_alert(org, Severity.CRITICAL)
        assert not should_alert(org, Severity.HIGH)


class TestSeverityRank:
    def test_ordering(self) -> None:
        assert SEVERITY_RANK[Severity.LOW] < SEVERITY_RANK[Severity.MEDIUM]
        assert SEVERITY_RANK[Severity.MEDIUM] < SEVERITY_RANK[Severity.HIGH]
        assert SEVERITY_RANK[Severity.HIGH] < SEVERITY_RANK[Severity.CRITICAL]
