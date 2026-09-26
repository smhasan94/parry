"""Send-time SSRF revalidation for alert dispatch.

Same TOCTOU shape as webhook delivery (Task 3): the URL was checked
when it was written to org.alert_config, but only revalidating here,
immediately before the network call, closes the window where the
config's DNS could be repointed in between.
"""

import pytest

from app.db.models import Incident
from app.services.alert_service import send_slack_alert, send_webhook_alert


@pytest.mark.asyncio
async def test_send_webhook_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    result = await send_webhook_alert("https://169.254.169.254/hook", sample_incident)
    assert result is False


@pytest.mark.asyncio
async def test_send_slack_alert_refuses_a_private_target(sample_incident: Incident) -> None:
    result = await send_slack_alert("https://10.0.0.5/hook", sample_incident)
    assert result is False
