"""Unit tests for the Slack bot service."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.db.models import Severity
from app.services.slack_bot_service import (
    build_action_response,
    build_block_kit_message,
)


def _make_incident(severity: Severity = Severity.HIGH, detections: int = 2) -> MagicMock:
    incident = MagicMock()
    incident.id = uuid4()
    incident.title = "Prompt injection detected"
    incident.severity = severity
    incident.status.value = "open"
    incident.agent_id = uuid4()
    incident.org_id = uuid4()
    incident.created_at = datetime(2026, 4, 12, 10, 30, 0, tzinfo=UTC)

    dets = []
    for i in range(detections):
        d = MagicMock()
        d.detector = f"detector_{i}"
        d.confidence = 0.9 - (i * 0.1)
        d.reason = f"Test reason {i}"
        d.severity = severity
        dets.append(d)
    incident.detections = dets
    return incident


def test_block_kit_has_header():
    msg = build_block_kit_message(_make_incident())
    blocks = msg["blocks"]
    headers = [b for b in blocks if b["type"] == "header"]
    assert len(headers) == 1
    assert "Prompt injection" in headers[0]["text"]["text"]


def test_block_kit_has_action_buttons():
    msg = build_block_kit_message(_make_incident())
    blocks = msg["blocks"]
    action_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(action_blocks) == 1
    buttons = action_blocks[0]["elements"]
    action_ids = {b["action_id"] for b in buttons}
    assert "parry_acknowledge" in action_ids
    assert "parry_escalate" in action_ids
    assert "parry_snooze" in action_ids


def test_block_kit_includes_dashboard_link():
    msg = build_block_kit_message(_make_incident(), dashboard_url="https://app.parry.dev")
    blocks = msg["blocks"]
    action_blocks = [b for b in blocks if b["type"] == "actions"]
    buttons = action_blocks[0]["elements"]
    urls = [b.get("url") for b in buttons if b.get("url")]
    assert any("parry.dev" in u for u in urls)


def test_block_kit_severity_color():
    for sev in [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]:
        msg = build_block_kit_message(_make_incident(severity=sev))
        assert "attachments" in msg
        assert msg["attachments"][0]["color"]


def test_block_kit_shows_detections():
    msg = build_block_kit_message(_make_incident(detections=3))
    blocks = msg["blocks"]
    section_texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
    assert any("Detections:" in t for t in section_texts)


def test_block_kit_no_detection_section_for_single():
    msg = build_block_kit_message(_make_incident(detections=1))
    blocks = msg["blocks"]
    section_texts = [b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section"]
    assert not any("Detections:" in t for t in section_texts)


def test_block_kit_has_context_footer():
    msg = build_block_kit_message(_make_incident())
    blocks = msg["blocks"]
    ctx = [b for b in blocks if b["type"] == "context"]
    assert len(ctx) == 1


def test_action_response_acknowledge():
    resp = build_action_response("parry_acknowledge", "abc123", "Alice")
    assert "Alice" in resp["text"]
    assert "acknowledged" in resp["text"]


def test_action_response_escalate():
    resp = build_action_response("parry_escalate", "abc123", "Bob")
    assert "Bob" in resp["text"]
    assert "escalated" in resp["text"]


def test_action_response_snooze():
    resp = build_action_response("parry_snooze", "abc123", "Carol")
    assert "Carol" in resp["text"]
    assert "snoozed" in resp["text"]


def test_action_response_unknown():
    resp = build_action_response("parry_unknown", "abc123", "Dave")
    assert "Dave" in resp["text"]
