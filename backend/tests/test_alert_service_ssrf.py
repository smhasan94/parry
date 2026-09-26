"""Send-time SSRF revalidation for alert dispatch.

Same TOCTOU shape as webhook delivery (Task 3): the URL was checked
when it was written to org.alert_config, but only revalidating here,
immediately before the network call, closes the window where the
config's DNS could be repointed in between.

``httpx.AsyncClient.post`` is patched to raise if it is ever reached, so
these tests fail fast and deterministically — independent of whatever a
given sandbox's network policy does with a real connection attempt to a
private address — if ``assert_public_https_url`` is ever removed or
bypassed.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Incident
from app.services.alert_service import send_slack_alert, send_webhook_alert

_NETWORK_CALL_ATTEMPTED = AssertionError(
    "httpx.AsyncClient.post was called — assert_public_https_url did not block "
    "the request before the network call, as it should have for this unsafe URL"
)


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
