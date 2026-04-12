"""Unit tests for the weekly digest service."""

from app.services.digest_service import compute_digest, render_digest_html


def _agents(grades: list[str]) -> list[dict]:
    return [
        {"id": f"agent-{i}", "name": f"Agent {i}", "health_grade": g}
        for i, g in enumerate(grades)
    ]


def _incidents(severities: list[str]) -> list[dict]:
    return [
        {"id": f"inc-{i}", "title": f"Incident {i}", "severity": s, "created_at": f"2026-04-{10+i}T00:00:00Z"}
        for i, s in enumerate(severities)
    ]


def test_fleet_health_breakdown():
    digest = compute_digest(
        agents=_agents(["A", "B", "C", "D", "F"]),
        incidents=[],
        events_7d=100, events_prev_7d=80,
        detections_7d=5, detections_prev_7d=3,
    )
    assert digest["fleet"]["total"] == 5
    assert digest["fleet"]["healthy"] == 2
    assert digest["fleet"]["degraded"] == 2
    assert digest["fleet"]["critical"] == 1


def test_event_trend_up():
    digest = compute_digest(
        agents=[], incidents=[],
        events_7d=200, events_prev_7d=100,
        detections_7d=0, detections_prev_7d=0,
    )
    assert digest["events"]["trend"] == "up"
    assert digest["events"]["change_pct"] == 100


def test_event_trend_down():
    digest = compute_digest(
        agents=[], incidents=[],
        events_7d=50, events_prev_7d=100,
        detections_7d=0, detections_prev_7d=0,
    )
    assert digest["events"]["trend"] == "down"
    assert digest["events"]["change_pct"] == 50


def test_event_trend_flat():
    digest = compute_digest(
        agents=[], incidents=[],
        events_7d=100, events_prev_7d=100,
        detections_7d=0, detections_prev_7d=0,
    )
    assert digest["events"]["trend"] == "flat"


def test_top_incidents_sorted_by_severity():
    digest = compute_digest(
        agents=[],
        incidents=_incidents(["low", "critical", "medium", "high"]),
        events_7d=0, events_prev_7d=0,
        detections_7d=0, detections_prev_7d=0,
    )
    top = digest["top_incidents"]
    assert top[0]["severity"] == "critical"
    assert top[1]["severity"] == "high"


def test_top_incidents_capped_at_5():
    digest = compute_digest(
        agents=[],
        incidents=_incidents(["high"] * 10),
        events_7d=0, events_prev_7d=0,
        detections_7d=0, detections_prev_7d=0,
    )
    assert len(digest["top_incidents"]) == 5


def test_attention_agents_filters_d_and_f():
    digest = compute_digest(
        agents=_agents(["A", "B", "C", "D", "F"]),
        incidents=[],
        events_7d=0, events_prev_7d=0,
        detections_7d=0, detections_prev_7d=0,
    )
    names = {a["name"] for a in digest["attention_agents"]}
    assert "Agent 3" in names  # grade D
    assert "Agent 4" in names  # grade F
    assert "Agent 0" not in names  # grade A


def test_render_html_contains_org_name():
    digest = compute_digest(
        agents=_agents(["A"]),
        incidents=[],
        events_7d=10, events_prev_7d=5,
        detections_7d=1, detections_prev_7d=0,
    )
    html = render_digest_html(digest, org_name="Acme Corp")
    assert "Acme Corp" in html
    assert "Parry Weekly Digest" in html


def test_render_html_includes_fleet_stats():
    digest = compute_digest(
        agents=_agents(["A", "F"]),
        incidents=[],
        events_7d=0, events_prev_7d=0,
        detections_7d=0, detections_prev_7d=0,
    )
    html = render_digest_html(digest)
    assert "Total agents" in html


def test_empty_digest():
    digest = compute_digest(
        agents=[], incidents=[],
        events_7d=0, events_prev_7d=0,
        detections_7d=0, detections_prev_7d=0,
    )
    assert digest["fleet"]["total"] == 0
    assert digest["top_incidents"] == []
    assert digest["attention_agents"] == []
