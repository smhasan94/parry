"""Fleet overview service — agent comparison and fleet-level metrics."""

from __future__ import annotations

from typing import Any


def compute_fleet_overview(agents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a fleet-level summary from agent data.

    Pure function — takes pre-fetched agent dicts with health info.
    """
    total = len(agents)
    if total == 0:
        return {
            "total_agents": 0,
            "grade_distribution": {},
            "avg_health_score": None,
            "agents": [],
        }

    # Grade distribution
    grades: dict[str, int] = {}
    scores = []
    for a in agents:
        g = a.get("health_grade") or "?"
        grades[g] = grades.get(g, 0) + 1
        if a.get("health_score") is not None:
            scores.append(a["health_score"])

    avg_score = round(sum(scores) / len(scores)) if scores else None

    # Sort agents: worst grade first, then by score ascending
    grade_rank = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "?": -1}
    sorted_agents = sorted(
        agents,
        key=lambda a: (
            grade_rank.get(a.get("health_grade") or "?", -1),
            a.get("health_score") or 0,
        ),
    )

    return {
        "total_agents": total,
        "grade_distribution": grades,
        "avg_health_score": avg_score,
        "agents": sorted_agents,
    }
