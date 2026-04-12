"""Unit tests for shareable incident report service."""

from app.services.incident_share_service import (
    build_share_report,
    generate_share_token,
    render_share_html,
    verify_share_token,
)


def test_token_generation_deterministic():
    t1 = generate_share_token("incident-123")
    t2 = generate_share_token("incident-123")
    assert t1 == t2


def test_token_different_for_different_incidents():
    t1 = generate_share_token("incident-123")
    t2 = generate_share_token("incident-456")
    assert t1 != t2


def test_token_length():
    token = generate_share_token("test")
    assert len(token) == 24


def test_verify_valid_token():
    token = generate_share_token("incident-abc")
    assert verify_share_token("incident-abc", token) is True


def test_verify_invalid_token():
    assert verify_share_token("incident-abc", "wrongtoken123456789012") is False


def test_build_share_report_structure():
    report = build_share_report(
        incident={"id": "inc-1", "title": "Test", "severity": "high", "status": "open", "created_at": "2026-04-12"},
        detections=[{"detector": "prompt_injection", "confidence": 0.9, "reason": "Injection detected"}],
        events=[{"id": "ev-1", "timestamp": "2026-04-12T10:00:00Z", "model": "gpt-4o", "tool_calls": []}],
    )
    assert "incident" in report
    assert "summary" in report
    assert "timeline" in report
    assert "recommendations" in report
    assert len(report["recommendations"]) > 0


def test_recommendations_for_prompt_injection():
    report = build_share_report(
        incident={"id": "inc-1", "title": "Test", "severity": "high", "status": "open"},
        detections=[{"detector": "prompt_injection"}],
        events=[],
    )
    assert any("system prompt" in r.lower() for r in report["recommendations"])


def test_recommendations_for_data_exfil():
    report = build_share_report(
        incident={"id": "inc-1", "title": "Test", "severity": "high", "status": "open"},
        detections=[{"detector": "data_exfiltration"}],
        events=[],
    )
    assert any("pii" in r.lower() or "credential" in r.lower() for r in report["recommendations"])


def test_render_html_contains_title():
    report = build_share_report(
        incident={"id": "inc-1", "title": "Critical Injection", "severity": "critical", "status": "open"},
        detections=[],
        events=[],
    )
    html = render_share_html(report)
    assert "Critical Injection" in html
    assert "CRITICAL" in html


def test_render_html_has_recommendations():
    report = build_share_report(
        incident={"id": "inc-1", "title": "Test", "severity": "low", "status": "open"},
        detections=[{"detector": "jailbreak"}],
        events=[],
    )
    html = render_share_html(report)
    assert "Recommendations" in html
    assert "<li" in html
