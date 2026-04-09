"""Tests for budget_service with mocked Redis and DB."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import budget_service


# ── record_spend ───────────────────────────────────────────────


def test_record_spend_increments_keys() -> None:
    """record_spend should INCRBYFLOAT on three keys with correct TTLs."""
    mock_pipe = MagicMock()
    mock_pipe.incrbyfloat = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = MagicMock(return_value=[])

    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    agent_id = uuid.uuid4()

    with patch.object(budget_service, "_get_redis", return_value=mock_redis):
        budget_service.record_spend(agent_id, 0.05)

    assert mock_pipe.incrbyfloat.call_count == 3
    assert mock_pipe.expire.call_count == 3
    mock_pipe.execute.assert_called_once()


def test_record_spend_zero_cost_skipped() -> None:
    """Zero or negative cost should be a no-op."""
    mock_redis = MagicMock()
    with patch.object(budget_service, "_get_redis", return_value=mock_redis):
        budget_service.record_spend(uuid.uuid4(), 0.0)
    mock_redis.pipeline.assert_not_called()


def test_record_spend_redis_unavailable() -> None:
    """Should not raise when Redis is down."""
    with patch.object(budget_service, "_get_redis", return_value=None):
        budget_service.record_spend(uuid.uuid4(), 1.0)  # should not raise


# ── get_spend ──────────────────────────────────────────────────


def test_get_spend_returns_value() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = "1.2345"

    agent_id = uuid.uuid4()

    with patch.object(budget_service, "_get_redis", return_value=mock_redis):
        result = budget_service.get_spend(agent_id, "hour")

    assert result == pytest.approx(1.2345)


def test_get_spend_missing_key() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch.object(budget_service, "_get_redis", return_value=mock_redis):
        result = budget_service.get_spend(uuid.uuid4(), "day")

    assert result == 0.0


def test_get_spend_invalid_period() -> None:
    assert budget_service.get_spend(uuid.uuid4(), "week") == 0.0


def test_get_spend_redis_unavailable() -> None:
    with patch.object(budget_service, "_get_redis", return_value=None):
        result = budget_service.get_spend(uuid.uuid4(), "month")
    assert result == 0.0


# ── check_spend ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_spend_no_budget_allows() -> None:
    """No budget configured → always allowed."""
    db = AsyncMock()
    with patch.object(budget_service, "_load_budget", new_callable=AsyncMock, return_value=None):
        allowed, reason = await budget_service.check_spend(db, uuid.uuid4())
    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_check_spend_under_budget() -> None:
    mock_budget = MagicMock()
    mock_budget.period = "day"
    mock_budget.cap_usd = 10.0

    db = AsyncMock()
    with (
        patch.object(
            budget_service, "_load_budget", new_callable=AsyncMock, return_value=mock_budget
        ),
        patch.object(budget_service, "get_spend", return_value=5.0),
    ):
        allowed, reason = await budget_service.check_spend(db, uuid.uuid4())
    assert allowed is True


@pytest.mark.asyncio
async def test_check_spend_over_budget() -> None:
    mock_budget = MagicMock()
    mock_budget.period = "hour"
    mock_budget.cap_usd = 1.0

    db = AsyncMock()
    with (
        patch.object(
            budget_service, "_load_budget", new_callable=AsyncMock, return_value=mock_budget
        ),
        patch.object(budget_service, "get_spend", return_value=0.96),
    ):
        allowed, reason = await budget_service.check_spend(db, uuid.uuid4())
    assert allowed is False
    assert reason is not None
    assert "Budget exceeded" in reason


@pytest.mark.asyncio
async def test_check_spend_fails_open_on_error() -> None:
    """If _load_budget raises, check_spend should fail open."""
    db = AsyncMock()
    with patch.object(
        budget_service,
        "_load_budget",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        allowed, reason = await budget_service.check_spend(db, uuid.uuid4())
    assert allowed is True
