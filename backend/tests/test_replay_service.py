"""Tests for replay_service — smart windowing, relevance scoring, and
the hypertable query bounds.

The scoring tests are pure logic. The loader tests use AsyncMock and
assert on the SQL the loader actually builds, because what is under
test is the shape of the query, not its result.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import replay_service
from app.services.replay_service import (
    MAX_WINDOW,
    NEAR_TRIGGER_RANGE,
    SCORE_HAS_DETECTIONS,
    SCORE_HAS_TOOL_CALLS,
    SCORE_HIGH_TOKENS,
    SCORE_NEAR_TRIGGER,
    SESSION_EVENT_CAP,
    EventAnnotation,
    ReplayEvent,
    score_event,
)

ANCHOR = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


def _scalars_returning(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_returning(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


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
            SCORE_HAS_DETECTIONS + SCORE_HAS_TOOL_CALLS + SCORE_HIGH_TOKENS + SCORE_NEAR_TRIGGER
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
            SCORE_HAS_DETECTIONS + SCORE_HAS_TOOL_CALLS + SCORE_HIGH_TOKENS + SCORE_NEAR_TRIGGER
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


class TestLoadSessionEvents:
    """``agent_events`` is a TimescaleDB hypertable partitioned on
    ``timestamp``. A predicate on ``session_id`` alone plans as a scan
    across every chunk, so the loader must always carry ``agent_id``,
    a bounded time range, and a row cap.
    """

    @pytest.mark.asyncio
    async def test_query_is_bounded_by_agent_time_and_row_cap(self) -> None:
        # Arrange
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([])

        # Act
        await replay_service._load_session_events(
            db,
            session_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            anchor=ANCHOR,
        )

        # Assert
        sql = str(db.execute.await_args[0][0])
        assert "agent_events.agent_id = " in sql
        assert "agent_events.session_id = " in sql
        assert "agent_events.timestamp >= " in sql
        assert "agent_events.timestamp <= " in sql
        assert "LIMIT" in sql

    @pytest.mark.asyncio
    async def test_returns_row_count_without_a_second_query_under_the_cap(
        self,
    ) -> None:
        # Arrange
        agent_id, session_id = uuid.uuid4(), uuid.uuid4()
        rows = [MagicMock() for _ in range(3)]
        db = AsyncMock()
        db.execute.return_value = _scalars_returning(rows)

        # Act
        events, total = await replay_service._load_session_events(
            db, session_id=session_id, agent_id=agent_id, anchor=ANCHOR
        )

        # Assert
        assert events == rows
        assert total == 3
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_counts_separately_when_the_cap_is_hit(self) -> None:
        # Arrange — a full page means the session may be larger than the
        # page, so the honest total needs its own COUNT.
        rows = [MagicMock() for _ in range(SESSION_EVENT_CAP)]
        db = AsyncMock()
        db.execute.side_effect = [
            _scalars_returning(rows),
            _scalar_returning(4_321),
        ]

        # Act
        events, total = await replay_service._load_session_events(
            db, session_id=uuid.uuid4(), agent_id=uuid.uuid4(), anchor=ANCHOR
        )

        # Assert
        assert len(events) == SESSION_EVENT_CAP
        assert total == 4_321
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_cap_exceeds_the_smart_window(self) -> None:
        """Scoring ranks events against each other, so the page must be
        wider than the window it feeds or the ranking is meaningless."""
        assert SESSION_EVENT_CAP > MAX_WINDOW


class TestLoadEvent:
    @pytest.mark.asyncio
    async def test_single_event_lookup_is_time_bounded(self) -> None:
        """``id`` alone is not the partition key — a bare id lookup
        scans every chunk just like an unbounded session query."""
        # Arrange
        db = AsyncMock()
        db.execute.return_value = _scalar_returning(None)

        # Act
        await replay_service._load_event(db, uuid.uuid4(), near=ANCHOR)

        # Assert
        sql = str(db.execute.await_args[0][0])
        assert "agent_events.id = " in sql
        assert "agent_events.timestamp >= " in sql
        assert "agent_events.timestamp <= " in sql
