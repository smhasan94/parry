"""Unit tests for agent health score.

Live DB-backed queries are exercised in e2e tests; here we lock down
the pure scoring function — penalty clamping, grade boundaries, the
new-agent-scores-100 contract, and anomaly clamping.
"""

from __future__ import annotations

import pytest

from app.services.health_score_service import _grade, compute_score

# ── Grade boundaries ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, "A"),
        (90, "A"),
        (89, "B"),
        (75, "B"),
        (74, "C"),
        (60, "C"),
        (59, "D"),
        (40, "D"),
        (39, "F"),
        (0, "F"),
    ],
)
def test_grade_boundaries(score: int, expected: str) -> None:
    assert _grade(score) == expected


# ── compute_score ────────────────────────────────────────────────────


def test_new_agent_scores_100() -> None:
    score, grade = compute_score(
        triggered_7d=0,
        open_incidents=0,
        critical_30d=0,
        anomaly_score=0.0,
    )
    assert score == 100
    assert grade == "A"


def test_triggered_detections_penalty_caps_at_50() -> None:
    # 20 triggered * 5 = 100, clamped to 50
    score, _ = compute_score(
        triggered_7d=20,
        open_incidents=0,
        critical_30d=0,
        anomaly_score=0.0,
    )
    assert score == 50


def test_open_incidents_penalty_caps_at_30() -> None:
    score, _ = compute_score(
        triggered_7d=0,
        open_incidents=10,  # 10 * 10 = 100, clamped to 30
        critical_30d=0,
        anomaly_score=0.0,
    )
    assert score == 70


def test_critical_incidents_penalty_caps_at_30() -> None:
    score, _ = compute_score(
        triggered_7d=0,
        open_incidents=0,
        critical_30d=5,  # 5 * 15 = 75, clamped to 30
        anomaly_score=0.0,
    )
    assert score == 70


def test_anomaly_contributes_up_to_20() -> None:
    score, _ = compute_score(
        triggered_7d=0,
        open_incidents=0,
        critical_30d=0,
        anomaly_score=1.0,
    )
    assert score == 80


def test_anomaly_clamped_below_zero() -> None:
    # Rogue detector result shouldn't raise the score above 100.
    score, _ = compute_score(
        triggered_7d=0,
        open_incidents=0,
        critical_30d=0,
        anomaly_score=-5.0,
    )
    assert score == 100


def test_anomaly_clamped_above_one() -> None:
    # Rogue detector result shouldn't drive extra penalty past 20.
    score, _ = compute_score(
        triggered_7d=0,
        open_incidents=0,
        critical_30d=0,
        anomaly_score=5.0,
    )
    assert score == 80


def test_score_never_goes_negative() -> None:
    score, grade = compute_score(
        triggered_7d=100,
        open_incidents=100,
        critical_30d=100,
        anomaly_score=1.0,
    )
    # 50 + 30 + 30 + 20 = 130 penalty, clamped to 0
    assert score == 0
    assert grade == "F"


def test_realistic_mixed_signal() -> None:
    # 3 triggered (15) + 1 open (10) + 0 critical + 0.25 anomaly (5) = 30
    score, grade = compute_score(
        triggered_7d=3,
        open_incidents=1,
        critical_30d=0,
        anomaly_score=0.25,
    )
    assert score == 70
    assert grade == "C"
