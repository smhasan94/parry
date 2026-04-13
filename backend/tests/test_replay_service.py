"""Tests for replay_service — smart windowing and relevance scoring.

Pure logic tests, no DB required.
"""

from app.services.replay_service import (
    MAX_WINDOW,
    NEAR_TRIGGER_RANGE,
    SCORE_HAS_DETECTIONS,
    SCORE_HAS_TOOL_CALLS,
    SCORE_HIGH_TOKENS,
    SCORE_NEAR_TRIGGER,
    EventAnnotation,
    ReplayEvent,
    score_event,
)


class TestScoreEvent:
    def test_trigger_gets_max_score(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=False,
            token_count_above_median=False,
            distance_from_trigger=0,
            is_trigger=True,
        )
        assert score == 100.0

    def test_detection_score(self) -> None:
        score = score_event(
            event_has_detections=True,
            event_has_tool_calls=False,
            token_count_above_median=False,
            distance_from_trigger=None,
            is_trigger=False,
        )
        assert score == SCORE_HAS_DETECTIONS

    def test_tool_calls_score(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=True,
            token_count_above_median=False,
            distance_from_trigger=None,
            is_trigger=False,
        )
        assert score == SCORE_HAS_TOOL_CALLS

    def test_high_tokens_score(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=False,
            token_count_above_median=True,
            distance_from_trigger=None,
            is_trigger=False,
        )
        assert score == SCORE_HIGH_TOKENS

    def test_near_trigger_score(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=False,
            token_count_above_median=False,
            distance_from_trigger=3,
            is_trigger=False,
        )
        assert score == SCORE_NEAR_TRIGGER

    def test_far_from_trigger_no_bonus(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=False,
            token_count_above_median=False,
            distance_from_trigger=NEAR_TRIGGER_RANGE + 1,
            is_trigger=False,
        )
        assert score == 0.0

    def test_all_signals_combined(self) -> None:
        score = score_event(
            event_has_detections=True,
            event_has_tool_calls=True,
            token_count_above_median=True,
            distance_from_trigger=1,
            is_trigger=False,
        )
        expected = (
            SCORE_HAS_DETECTIONS
            + SCORE_HAS_TOOL_CALLS
            + SCORE_HIGH_TOKENS
            + SCORE_NEAR_TRIGGER
        )
        assert score == expected

    def test_no_signals(self) -> None:
        score = score_event(
            event_has_detections=False,
            event_has_tool_calls=False,
            token_count_above_median=False,
            distance_from_trigger=None,
            is_trigger=False,
        )
        assert score == 0.0

    def test_trigger_overrides_all(self) -> None:
        """Trigger score (100) should always be higher than any combination."""
        max_non_trigger = (
            SCORE_HAS_DETECTIONS
            + SCORE_HAS_TOOL_CALLS
            + SCORE_HIGH_TOKENS
            + SCORE_NEAR_TRIGGER
        )
        assert max_non_trigger < 100.0


class TestScoreWeights:
    def test_detections_highest_weight(self) -> None:
        assert SCORE_HAS_DETECTIONS > SCORE_HAS_TOOL_CALLS
        assert SCORE_HAS_DETECTIONS > SCORE_HIGH_TOKENS
        assert SCORE_HAS_DETECTIONS > SCORE_NEAR_TRIGGER

    def test_tool_calls_second_highest(self) -> None:
        assert SCORE_HAS_TOOL_CALLS > SCORE_HIGH_TOKENS
        assert SCORE_HAS_TOOL_CALLS > SCORE_NEAR_TRIGGER


class TestConstants:
    def test_max_window(self) -> None:
        assert MAX_WINDOW == 50

    def test_near_trigger_range(self) -> None:
        assert NEAR_TRIGGER_RANGE == 5


class TestEventAnnotation:
    def test_default_empty(self) -> None:
        a = EventAnnotation()
        assert a.detections == []
        assert a.permission_violations == []
        assert a.threat_intel_matches == []
        assert a.relevance_score == 0.0

    def test_with_data(self) -> None:
        a = EventAnnotation(
            detections=[{"detector": "prompt_injection", "severity": "high"}],
            permission_violations=["get_secret: Tool explicitly blocked"],
            threat_intel_matches=["abc123"],
            relevance_score=5.0,
        )
        assert len(a.detections) == 1
        assert len(a.permission_violations) == 1
        assert len(a.threat_intel_matches) == 1


class TestReplayEvent:
    def test_trigger_event(self) -> None:
        e = ReplayEvent(
            id="evt-1",
            timestamp="2026-04-10T10:00:00Z",
            model="gpt-4o",
            prompt_preview="Hello...",
            response_preview="World...",
            prompt=None,
            response=None,
            tool_calls=[{"name": "search_kb"}],
            token_count=500,
            is_trigger=True,
            annotations=EventAnnotation(relevance_score=100.0),
        )
        assert e.is_trigger is True
        assert e.annotations.relevance_score == 100.0

    def test_normal_event(self) -> None:
        e = ReplayEvent(
            id="evt-2",
            timestamp="2026-04-10T09:59:00Z",
            model="gpt-4o",
            prompt_preview="What is...",
            response_preview="The answer...",
            prompt=None,
            response=None,
            tool_calls=None,
            token_count=200,
            is_trigger=False,
            annotations=EventAnnotation(),
        )
        assert e.is_trigger is False
        assert e.tool_calls is None
