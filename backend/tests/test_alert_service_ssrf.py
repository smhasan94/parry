"""Send-time SSRF revalidation for alert dispatch.

Same TOCTOU shape as webhook delivery (Task 3): the URL was checked
when it was written to org.alert_config, but its DNS can be repointed
any time after that. Revalidating here, immediately before the network
call, narrows that window from "since the config was saved" to the
milliseconds between the validator's lookup and httpx's own, separate
lookup when it connects. It does not close it: a nameserver answering
with TTL 0 can still say "public" to the first lookup and "private" to
the second. What bounds that residual case is https-only plus httpx's
default certificate verification — an internal target cannot present a
valid certificate for the attacker's hostname, so the handshake fails
before any payload is sent.

``httpx.AsyncClient.post`` is patched to raise if it is ever reached, so
these tests fail fast and deterministically — independent of whatever a
given sandbox's network policy does with a real connection attempt to a
private address — if ``assert_public_https_url`` is ever removed or
bypassed.
"""

import threading
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Incident
from app.services.alert_service import (
    BudgetAlertContext,
    dispatch_budget_alert,
    send_slack_alert,
    send_webhook_alert,
)

_NETWORK_CALL_ATTEMPTED = AssertionError(
    "httpx.AsyncClient.post was called — assert_public_https_url did not block "
    "the request before the network call, as it should have for this unsafe URL"
)

_PUBLIC_IP = "93.184.216.34"


def _budget_ctx() -> BudgetAlertContext:
    return BudgetAlertContext(
        budget_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_name="spend-bot",
        org_id=uuid.uuid4(),
        period="day",
        cap_usd=0.01,
        current_spend=0.009,
        threshold_pct=80,
    )


def _org_with(alert_config: dict[str, Any]) -> MagicMock:
    org = MagicMock()
    org.alert_config = alert_config
    return org


def _ok_post() -> AsyncMock:
    return AsyncMock(return_value=MagicMock(status_code=200))


def _assert_all_off_loop(thread_ids: list[int]) -> None:
    loop_thread = threading.get_ident()
    assert thread_ids, "resolver was never called"
    assert all(thread != loop_thread for thread in thread_ids)


@pytest.mark.asyncio
async def test_send_webhook_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=_NETWORK_CALL_ATTEMPTED,
    ) as mock_post:
        result = await send_webhook_alert("https://169.254.169.254/hook", sample_incident)

    assert result is False
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_slack_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=_NETWORK_CALL_ATTEMPTED,
    ) as mock_post:
        result = await send_slack_alert("https://10.0.0.5/hook", sample_incident)

    assert result is False
    mock_post.assert_not_called()


# ── Budget alerts ─────────────────────────────────────────────────
# Reachable from any tenant's /api/v1/proxy/check once a budget
# threshold is crossed, so it gets the same send-time check.


@pytest.mark.asyncio
async def test_dispatch_budget_alert_refuses_private_targets() -> None:
    org = _org_with(
        {
            "slack_webhook_url": "https://10.0.0.5/hook",
            "webhook_url": "https://169.254.169.254/hook",
        }
    )
    with (
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=_NETWORK_CALL_ATTEMPTED,
        ) as mock_post,
        patch("app.services.alert_service.record_alert_sent") as mock_record,
    ):
        await dispatch_budget_alert(org, _budget_ctx())

    mock_post.assert_not_called()
    mock_record.assert_any_call(channel="slack", success=False)
    mock_record.assert_any_call(channel="webhook", success=False)


@pytest.mark.asyncio
async def test_dispatch_budget_alert_still_sends_to_public_targets() -> None:
    slack_url = f"https://{_PUBLIC_IP}/slack"
    webhook_url = f"https://{_PUBLIC_IP}/hook"
    org = _org_with(
        {
            "slack_webhook_url": slack_url,
            "webhook_url": webhook_url,
            "webhook_headers": {"X-Token": "abc"},
        }
    )
    with patch("httpx.AsyncClient.post", new_callable=_ok_post) as mock_post:
        await dispatch_budget_alert(org, _budget_ctx())

    posted_to = [call.args[0] for call in mock_post.await_args_list]
    assert posted_to == [slack_url, webhook_url]
    webhook_call = mock_post.await_args_list[1]
    assert webhook_call.kwargs["json"]["event"] == "budget.threshold_crossed"
    assert webhook_call.kwargs["headers"] == {"X-Token": "abc"}


# ── Off-loop resolution ───────────────────────────────────────────
# All three run on uvicorn's loop in at least one path (POST /alerts/test,
# /proxy/check's budget alerts), so a slow nameserver must not stall it.


@pytest.mark.asyncio
async def test_send_slack_alert_resolves_off_the_event_loop(
    sample_incident: Incident, resolver_thread_ids: list[int]
) -> None:
    with patch("httpx.AsyncClient.post", new_callable=_ok_post):
        assert await send_slack_alert("https://hooks.example/slack", sample_incident)

    _assert_all_off_loop(resolver_thread_ids)


@pytest.mark.asyncio
async def test_send_webhook_alert_resolves_off_the_event_loop(
    sample_incident: Incident, resolver_thread_ids: list[int]
) -> None:
    with patch("httpx.AsyncClient.post", new_callable=_ok_post):
        assert await send_webhook_alert("https://hooks.example/hook", sample_incident)

    _assert_all_off_loop(resolver_thread_ids)


@pytest.mark.asyncio
async def test_dispatch_budget_alert_resolves_off_the_event_loop(
    resolver_thread_ids: list[int],
) -> None:
    org = _org_with(
        {
            "slack_webhook_url": "https://hooks.example/slack",
            "webhook_url": "https://hooks.example/hook",
        }
    )
    with patch("httpx.AsyncClient.post", new_callable=_ok_post) as mock_post:
        await dispatch_budget_alert(org, _budget_ctx())

    assert mock_post.await_count == 2
    assert len(resolver_thread_ids) == 2
    _assert_all_off_loop(resolver_thread_ids)
