"""Unit tests for the compliance report service + template.

DB-backed assembly (``build_report_data`` over a real Postgres) is
exercised in e2e tests; here we lock down:

* argument validation on ``build_report_data``
* the HTML template renders every section deterministically
* no raw prompt/response content ever leaks through the renderer
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.services.report_service import build_report_data
from app.services.report_template import render_report_html


# ── build_report_data input guards ───────────────────────────────────


@pytest.mark.asyncio
async def test_build_report_data_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await build_report_data(
            db=None,  # type: ignore[arg-type]
            org_id=uuid.uuid4(),
            start=datetime(2026, 1, 1),
            end=datetime(2026, 2, 1, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_build_report_data_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        await build_report_data(
            db=None,  # type: ignore[arg-type]
            org_id=uuid.uuid4(),
            start=datetime(2026, 2, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, tzinfo=UTC),
        )


# ── Template rendering ───────────────────────────────────────────────


@pytest.fixture
def sample_report_data() -> dict:
    return {
        "org": {"id": "11111111-1111-1111-1111-111111111111", "name": "Acme AI"},
        "period": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"},
        "generated_at": "2026-02-01T12:34:00+00:00",
        "summary": {
            "total_events": 12345,
            "total_detections": 200,
            "triggered_detections": 37,
            "total_incidents": 4,
            "agents_monitored": 3,
        },
        "detections_by_severity": {"critical": 2, "high": 10, "medium": 20, "low": 5},
        "detections_by_detector": {"prompt_injection": 25, "jailbreak": 12},
        "incidents": [
            {
                "id": "abc",
                "title": "[HIGH] prompt_injection: test",
                "severity": "high",
                "status": "open",
                "created_at": "2026-01-05T10:00:00+00:00",
                "resolved_at": None,
            }
        ],
        "policies": [
            {
                "name": "default",
                "is_active": True,
                "allowed_tools": ["search"],
                "blocked_tools": ["exec_code"],
                "allowed_domains": [],
                "blocked_domains": ["evil.example"],
                "max_token_budget": 100_000,
                "forbidden_patterns": ["pat1", "pat2"],
            }
        ],
        "agents": [
            {
                "id": "agent-1",
                "name": "support-bot",
                "event_count": 9000,
                "incident_count": 3,
                "is_active": True,
            },
            {
                "id": "agent-2",
                "name": "dormant-bot",
                "event_count": 0,
                "incident_count": 0,
                "is_active": False,
            },
        ],
    }


def test_template_renders_all_sections(sample_report_data: dict) -> None:
    html = render_report_html(sample_report_data)

    # Cover + org branding
    assert "Parry" in html
    assert "Acme AI" in html
    assert "Compliance Report" in html

    # Summary numbers
    assert "12345" in html  # total events
    assert "37" in html  # triggered detections

    # Severity table (all four rows, even zero-count ones)
    assert "Critical" in html
    assert "High" in html
    assert "Medium" in html
    assert "Low" in html

    # Detector breakdown
    assert "prompt_injection" in html
    assert "jailbreak" in html

    # Incidents table
    assert "[HIGH] prompt_injection: test" in html

    # Policies
    assert "default" in html
    assert "100000" in html
    assert "2 configured" in html  # forbidden patterns summary

    # Agents
    assert "support-bot" in html
    assert "dormant-bot" in html
    assert "Inactive" in html

    # Footer compliance disclaimer
    assert "GDPR" in html
    assert "minimization" in html


def test_template_handles_empty_collections() -> None:
    data = {
        "org": {"id": "x", "name": "Empty Org"},
        "period": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-02T00:00:00+00:00"},
        "generated_at": "2026-01-02T00:00:00+00:00",
        "summary": {
            "total_events": 0,
            "total_detections": 0,
            "triggered_detections": 0,
            "total_incidents": 0,
            "agents_monitored": 0,
        },
        "detections_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "detections_by_detector": {},
        "incidents": [],
        "policies": [],
        "agents": [],
    }
    html = render_report_html(data)
    assert "No triggered detections" in html
    assert "No incidents recorded" in html
    assert "No policies configured" in html
    assert "No agents registered" in html


def test_template_escapes_html_in_untrusted_fields() -> None:
    data = {
        "org": {"id": "x", "name": "<script>alert(1)</script>"},
        "period": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-02T00:00:00+00:00"},
        "generated_at": "2026-01-02T00:00:00+00:00",
        "summary": {
            "total_events": 0,
            "total_detections": 0,
            "triggered_detections": 0,
            "total_incidents": 0,
            "agents_monitored": 0,
        },
        "detections_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "detections_by_detector": {},
        "incidents": [
            {
                "id": "x",
                "title": "<img src=x onerror=1>",
                "severity": "high",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
                "resolved_at": None,
            }
        ],
        "policies": [],
        "agents": [],
    }
    html = render_report_html(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=1>" not in html
    assert "&lt;img" in html


def test_template_never_includes_raw_prompt_keys(sample_report_data: dict) -> None:
    """Defense in depth: even if callers accidentally smuggle prompt/
    response fields into the data dict, the template should not render
    them (it has no section that reads those keys)."""
    tainted = dict(sample_report_data)
    tainted["__leaked_prompt__"] = "SECRET PROMPT: api key sk-123"
    html = render_report_html(tainted)
    assert "SECRET PROMPT" not in html
    assert "sk-123" not in html
