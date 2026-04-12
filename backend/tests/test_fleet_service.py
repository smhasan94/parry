"""Unit tests for fleet overview service."""

from app.services.fleet_service import compute_fleet_overview


def _agents(data: list[tuple[str, str, int]]) -> list[dict]:
    return [
        {"id": f"a-{i}", "name": n, "health_grade": g, "health_score": s}
        for i, (n, g, s) in enumerate(data)
    ]


def test_empty_fleet():
    result = compute_fleet_overview([])
    assert result["total_agents"] == 0
    assert result["avg_health_score"] is None


def test_grade_distribution():
    agents = _agents([("a1", "A", 95), ("a2", "A", 92), ("a3", "B", 80), ("a4", "F", 20)])
    result = compute_fleet_overview(agents)
    assert result["grade_distribution"]["A"] == 2
    assert result["grade_distribution"]["B"] == 1
    assert result["grade_distribution"]["F"] == 1


def test_avg_health_score():
    agents = _agents([("a1", "A", 100), ("a2", "F", 0)])
    result = compute_fleet_overview(agents)
    assert result["avg_health_score"] == 50


def test_agents_sorted_worst_first():
    agents = _agents([("good", "A", 95), ("bad", "F", 10), ("ok", "C", 60)])
    result = compute_fleet_overview(agents)
    assert result["agents"][0]["name"] == "bad"
    assert result["agents"][-1]["name"] == "good"


def test_total_count():
    agents = _agents([("a", "A", 90)] * 5)
    result = compute_fleet_overview(agents)
    assert result["total_agents"] == 5
