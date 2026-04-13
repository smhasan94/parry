"""Unit tests for budget threshold alert dedup and dispatch logic.

Mocks Redis and alert_service.dispatch_budget_alert to verify:
  - Crossing a threshold fires an alert.
  - Crossing the same threshold twice doesn't fire a duplicate.
  - Different thresholds fire independently.
  - A new period resets the alert state (dedup key changes).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import budget_service
from app.services.alert_service import BudgetAlertContext

# ── helpers ───────────────────────────────────────────────────────


def _make_budget(
    pcts: list[int],
    cap_usd: float = 10.0,
    period: str = "day",
) -> MagicMock:
    budget = MagicMock()
    budget.id = uuid.uuid4()
    budget.org_id = uuid.uuid4()
    budget.period = period
    budget.cap_usd = cap_usd
    budget.alert_at_pcts = pcts
    return budget


def _make_agent(name: str = "test-agent") -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = name
    return agent


def _make_org() -> MagicMock:
    org = MagicMock()
    org.id = uuid.uuid4()
    org.alert_config = {"slack_webhook_url": "https://hooks.slack.com/test"}
    return org


# ── _check_and_mark_threshold ─────────────────────────────────────


def test_check_and_mark_returns_true_first_time() -> None:
    """First call should set the key and return True (should fire)."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # NX succeeded

    budget_id = uuid.uuid4()
    result = budget_service._check_and_mark_threshold(mock_redis, budget_id, "day", 80)

    assert result is True
    mock_redis.set.assert_called_once()
    call_kwargs = mock_redis.set.call_args
    assert call_kwargs.kwargs.get("nx") is True


def test_check_and_mark_returns_false_second_time() -> None:
    """Second call (key already exists) should return False (do not re-fire)."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = None  # NX failed — key already set

    budget_id = uuid.uuid4()
    result = budget_service._check_and_mark_threshold(mock_redis, budget_id, "day", 80)

    assert result is False


def test_check_and_mark_redis_error_returns_false() -> None:
    """Redis errors should be swallowed and return False (fail safe — don't spam)."""
    mock_redis = MagicMock()
    mock_redis.set.side_effect = ConnectionError("redis down")

    result = budget_service._check_and_mark_threshold(mock_redis, uuid.uuid4(), "hour", 90)

    assert result is False


# ── _current_period_key ───────────────────────────────────────────


def test_period_key_changes_across_periods() -> None:
    """Two calls in the same period should give identical keys."""

    with patch("time.time", return_value=1_000_000.0):
        key_a = budget_service._current_period_key("hour")
    with patch("time.time", return_value=1_000_001.0):
        key_b = budget_service._current_period_key("hour")

    assert key_a == key_b  # same hour bucket


def test_period_key_differs_across_hours() -> None:
    with patch("time.time", return_value=0.0):
        key_a = budget_service._current_period_key("hour")
    with patch("time.time", return_value=3_601.0):
        key_b = budget_service._current_period_key("hour")

    assert key_a != key_b


# ── _fire_threshold_alerts ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_threshold_alerts_dispatches_when_crossed() -> None:
    """When spend is above a configured threshold, dispatch_budget_alert is called."""
    budget = _make_budget(pcts=[80], cap_usd=10.0, period="day")
    agent = _make_agent()
    org = _make_org()
    db = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # NX succeeds — first time

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch.object(budget_service, "_load_org", new_callable=AsyncMock, return_value=org),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        # current_spend = 8.5 → 85% of $10 cap → crosses 80%
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=8.5)

    mock_dispatch.assert_called_once()
    ctx: BudgetAlertContext = mock_dispatch.call_args.args[1]
    assert ctx.threshold_pct == 80
    assert ctx.current_spend == pytest.approx(8.5)
    assert ctx.cap_usd == pytest.approx(10.0)
    assert ctx.agent_name == agent.name


@pytest.mark.asyncio
async def test_fire_threshold_alerts_no_duplicate_for_same_threshold() -> None:
    """If the dedup key is already set, dispatch_budget_alert is NOT called again."""
    budget = _make_budget(pcts=[80], cap_usd=10.0, period="day")
    agent = _make_agent()
    org = _make_org()
    db = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.set.return_value = None  # NX failed — already fired

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch.object(budget_service, "_load_org", new_callable=AsyncMock, return_value=org),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=8.5)

    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_fire_threshold_alerts_different_thresholds_fire_independently() -> None:
    """Each threshold has its own dedup key and fires independently."""
    budget = _make_budget(pcts=[50, 80, 90], cap_usd=10.0, period="day")
    agent = _make_agent()
    org = _make_org()
    db = AsyncMock()

    mock_redis = MagicMock()
    # 50% and 80% already fired; 90% is new
    fired_keys: set[str] = set()

    def nx_set(key: str, value: str, nx: bool, ex: int) -> bool | None:
        if "50" in key or "80" in key:
            return None  # already set
        fired_keys.add(key)
        return True  # new

    mock_redis.set.side_effect = nx_set

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch.object(budget_service, "_load_org", new_callable=AsyncMock, return_value=org),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        # 9.5 / 10 = 95% → all three thresholds crossed
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=9.5)

    # Only 90% should have been dispatched
    assert mock_dispatch.call_count == 1
    ctx: BudgetAlertContext = mock_dispatch.call_args.args[1]
    assert ctx.threshold_pct == 90


@pytest.mark.asyncio
async def test_fire_threshold_alerts_new_period_resets_state() -> None:
    """Alerts fired in period A do not suppress alerts in period B."""
    budget = _make_budget(pcts=[80], cap_usd=10.0, period="hour")
    agent = _make_agent()
    org = _make_org()
    db = AsyncMock()

    # Simulate two different hour buckets
    hour_one_key_set: set[str] = set()

    def nx_set_hour_one(key: str, value: str, nx: bool, ex: int) -> bool | None:
        if key in hour_one_key_set:
            return None
        hour_one_key_set.add(key)
        return True

    mock_redis = MagicMock()
    mock_redis.set.side_effect = nx_set_hour_one

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch.object(budget_service, "_load_org", new_callable=AsyncMock, return_value=org),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
        # Lock time to hour bucket 277 (arbitrary)
        patch("time.time", return_value=277 * 3600.0),
    ):
        # First call — should fire
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=8.5)
        # Second call same period — should NOT fire (NX fails because key exists)
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=9.0)

    assert mock_dispatch.call_count == 1

    # Now advance to next hour bucket — dedup key is different → should fire again
    mock_dispatch.reset_mock()
    hour_one_key_set.clear()  # simulate TTL expiry by clearing our tracking set

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch.object(budget_service, "_load_org", new_callable=AsyncMock, return_value=org),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch2,
        # Different hour bucket
        patch("time.time", return_value=278 * 3600.0),
    ):
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=8.5)

    assert mock_dispatch2.call_count == 1


@pytest.mark.asyncio
async def test_fire_threshold_alerts_not_crossed_does_not_fire() -> None:
    """When spend is below all configured thresholds, no alerts are dispatched."""
    budget = _make_budget(pcts=[80, 90], cap_usd=10.0, period="day")
    agent = _make_agent()
    db = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with (
        patch.object(budget_service, "_get_redis", return_value=mock_redis),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        # 5.0 / 10.0 = 50% — below both thresholds
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=5.0)

    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_fire_threshold_alerts_no_redis_skips_silently() -> None:
    """When Redis is unavailable, the function returns without raising."""
    budget = _make_budget(pcts=[80], cap_usd=10.0, period="day")
    agent = _make_agent()
    db = AsyncMock()

    with (
        patch.object(budget_service, "_get_redis", return_value=None),
        patch(
            "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=9.0)

    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_fire_threshold_alerts_empty_pcts_skips() -> None:
    """Empty alert_at_pcts list means no alerts ever fire."""
    budget = _make_budget(pcts=[], cap_usd=10.0, period="day")
    agent = _make_agent()
    db = AsyncMock()

    with patch(
        "app.services.budget_service.dispatch_budget_alert", new_callable=AsyncMock
    ) as mock_dispatch:
        await budget_service._fire_threshold_alerts(db, budget, agent, current_spend=9.9)

    mock_dispatch.assert_not_called()
