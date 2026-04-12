"""Unit tests for SDK integration health service."""

from datetime import UTC, datetime, timedelta

from app.services.sdk_health_service import compute_sdk_health


def _now():
    return datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC)


def test_healthy_agent():
    agents = [{"id": "a1", "name": "Agent 1", "last_event_at": (_now() - timedelta(minutes=30)).isoformat()}]
    result = compute_sdk_health(agents, now=_now())
    assert result["healthy"] == 1
    assert result["agents"][0]["status"] == "healthy"


def test_stale_agent():
    agents = [{"id": "a1", "name": "Agent 1", "last_event_at": (_now() - timedelta(hours=5)).isoformat()}]
    result = compute_sdk_health(agents, now=_now())
    assert result["stale"] == 1
    assert result["agents"][0]["status"] == "stale"


def test_silent_agent():
    agents = [{"id": "a1", "name": "Agent 1", "last_event_at": None}]
    result = compute_sdk_health(agents, now=_now())
    assert result["silent"] == 1
    assert result["agents"][0]["status"] == "silent"


def test_mixed_fleet():
    agents = [
        {"id": "a1", "name": "Healthy", "last_event_at": (_now() - timedelta(minutes=10)).isoformat()},
        {"id": "a2", "name": "Stale", "last_event_at": (_now() - timedelta(hours=6)).isoformat()},
        {"id": "a3", "name": "Silent", "last_event_at": None},
    ]
    result = compute_sdk_health(agents, now=_now())
    assert result["total"] == 3
    assert result["healthy"] == 1
    assert result["stale"] == 1
    assert result["silent"] == 1


def test_sorted_worst_first():
    agents = [
        {"id": "a1", "name": "Healthy", "last_event_at": (_now() - timedelta(minutes=5)).isoformat()},
        {"id": "a2", "name": "Silent", "last_event_at": None},
        {"id": "a3", "name": "Stale", "last_event_at": (_now() - timedelta(hours=4)).isoformat()},
    ]
    result = compute_sdk_health(agents, now=_now())
    assert result["agents"][0]["name"] == "Silent"
    assert result["agents"][-1]["name"] == "Healthy"


def test_empty_fleet():
    result = compute_sdk_health([], now=_now())
    assert result["total"] == 0
    assert result["healthy"] == 0
