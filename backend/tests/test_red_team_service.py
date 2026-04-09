"""Pure-function tests for red_team_service.

The DB-backed CRUD helpers (`start_run`, `get_run`, `list_runs`,
`list_results`) are exercised in the e2e suite. Here we lock down
the pure scoring function — grade boundaries, per-category math,
and the empty-corpus edge case.
"""

from __future__ import annotations

import pytest

from app.services.red_team_service import grade_for, score_results


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, "A"),
        (95, "A"),
        (94, "B"),
        (85, "B"),
        (84, "C"),
        (70, "C"),
        (69, "D"),
        (50, "D"),
        (49, "F"),
        (0, "F"),
    ],
)
def test_grade_boundaries(score: int, expected: str) -> None:
    assert grade_for(score) == expected


def test_score_empty_results() -> None:
    stats = score_results([])
    assert stats == {
        "total": 0,
        "detected": 0,
        "score": 0,
        "grade": "F",
        "by_category": {},
    }


def test_score_all_caught() -> None:
    results = [
        {"category": "jailbreak", "detected": True, "attack_id": "a", "severity": "high"},
        {"category": "jailbreak", "detected": True, "attack_id": "b", "severity": "high"},
    ]
    stats = score_results(results)
    assert stats["score"] == 100
    assert stats["grade"] == "A"
    assert stats["by_category"] == {"jailbreak": 100}


def test_score_partial_per_category() -> None:
    results = [
        {"category": "jailbreak", "detected": True, "attack_id": "j1", "severity": "high"},
        {"category": "jailbreak", "detected": False, "attack_id": "j2", "severity": "high"},
        {"category": "jailbreak", "detected": True, "attack_id": "j3", "severity": "high"},
        {"category": "data_exfil", "detected": True, "attack_id": "d1", "severity": "high"},
        {"category": "data_exfil", "detected": True, "attack_id": "d2", "severity": "high"},
    ]
    stats = score_results(results)
    assert stats["total"] == 5
    assert stats["detected"] == 4
    assert stats["score"] == 80
    assert stats["grade"] == "C"
    assert stats["by_category"] == {"jailbreak": 67, "data_exfil": 100}
