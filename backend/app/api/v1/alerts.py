"""Alert config API — manage Slack webhook and severity thresholds per org."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.core.rbac import Role, require_role
from app.core.url_safety import assert_public_https_url
from app.db.models import Detection, Incident, IncidentStatus, Org, Severity
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service
from app.services.alert_service import (
    send_email_alert,
    send_opsgenie_alert,
    send_pagerduty_alert,
    send_slack_alert,
    send_webhook_alert,
)

log = structlog.get_logger()

router = APIRouter()


class AlertConfigResponse(ParrySchema):
    slack_webhook_url: str | None = None
    alert_emails: list[str] = []
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = {}
    # PagerDuty/Opsgenie keys are never returned in cleartext — the UI
    # only ever needs to know whether one is configured, so we surface
    # a masked preview ("******abcd") that's safe to log.
    pagerduty_routing_key: str | None = None
    opsgenie_api_key: str | None = None
    min_severity: str = "high"
    enabled: bool = False


class AlertConfigUpdate(ParrySchema):
    slack_webhook_url: HttpUrl | None = None
    alert_emails: list[EmailStr] | None = None
    webhook_url: HttpUrl | None = None
    webhook_headers: dict[str, str] | None = None
    pagerduty_routing_key: str | None = None
    opsgenie_api_key: str | None = None
    min_severity: str | None = None


def _mask_secret(value: str | None) -> str | None:
    """Return a safe preview of a secret — never the cleartext value."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def _config_to_response(config: dict[str, Any] | None) -> AlertConfigResponse:
    config = config or {}
    return AlertConfigResponse(
        slack_webhook_url=config.get("slack_webhook_url"),
        alert_emails=config.get("alert_emails") or [],
        webhook_url=config.get("webhook_url"),
        webhook_headers=config.get("webhook_headers") or {},
        pagerduty_routing_key=_mask_secret(config.get("pagerduty_routing_key")),
        opsgenie_api_key=_mask_secret(config.get("opsgenie_api_key")),
        min_severity=config.get("min_severity", "high"),
        enabled=bool(
            config.get("slack_webhook_url")
            or config.get("alert_emails")
            or config.get("webhook_url")
            or config.get("pagerduty_routing_key")
            or config.get("opsgenie_api_key")
        ),
    )


@router.get(
    "",
    response_model=AlertConfigResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_alert_config(
    org: Org = Depends(get_current_org),
) -> AlertConfigResponse:
    """Get the current alert configuration for the org."""
    return _config_to_response(org.alert_config)


def _redact_webhook(url: str | None) -> str | None:
    """Mask the secret portion of a webhook URL for audit logs."""
    if not url:
        return url
    if len(url) <= 40:
        return url[:20] + "..."
    return url[:30] + "..." + url[-6:]


def _audit_safe_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of the alert config safe to write to the audit log."""
    cfg = dict(config or {})
    if "slack_webhook_url" in cfg:
        cfg["slack_webhook_url"] = _redact_webhook(cfg.get("slack_webhook_url"))
    if "webhook_url" in cfg:
        cfg["webhook_url"] = _redact_webhook(cfg.get("webhook_url"))
    if "webhook_headers" in cfg and cfg["webhook_headers"]:
        # Header values may carry tokens — keep keys, redact values
        cfg["webhook_headers"] = {k: "[Filtered]" for k in cfg["webhook_headers"]}
    if "pagerduty_routing_key" in cfg:
        cfg["pagerduty_routing_key"] = _mask_secret(cfg.get("pagerduty_routing_key"))
    if "opsgenie_api_key" in cfg:
        cfg["opsgenie_api_key"] = _mask_secret(cfg.get("opsgenie_api_key"))
    return cfg


@router.put(
    "",
    response_model=AlertConfigResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_alert_config(
    body: AlertConfigUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AlertConfigResponse:
    """Update the alert configuration for the org."""
    org, actor = org_actor
    before = dict(org.alert_config or {})
    config = dict(before)

    if body.slack_webhook_url is not None:
        config["slack_webhook_url"] = str(body.slack_webhook_url)
        assert_public_https_url(config["slack_webhook_url"])

    if body.alert_emails is not None:
        config["alert_emails"] = [str(e) for e in body.alert_emails]

    if body.webhook_url is not None:
        config["webhook_url"] = str(body.webhook_url)
        assert_public_https_url(config["webhook_url"])

    if body.webhook_headers is not None:
        config["webhook_headers"] = body.webhook_headers

    if body.pagerduty_routing_key is not None:
        # Empty string is treated as "clear this integration" so the UI
        # can disable PagerDuty without a separate DELETE.
        if body.pagerduty_routing_key:
            config["pagerduty_routing_key"] = body.pagerduty_routing_key
        else:
            config.pop("pagerduty_routing_key", None)

    if body.opsgenie_api_key is not None:
        if body.opsgenie_api_key:
            config["opsgenie_api_key"] = body.opsgenie_api_key
        else:
            config.pop("opsgenie_api_key", None)

    if body.min_severity is not None:
        try:
            Severity(body.min_severity)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"min_severity must be one of: {', '.join(s.value for s in Severity)}",
            ) from None
        config["min_severity"] = body.min_severity

    org.alert_config = config
    await db.flush()
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="alert_config.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="alert_config",
        details={
            "before": _audit_safe_config(before),
            "after": _audit_safe_config(config),
        },
    )
    await db.commit()
    log.info("alert_config.updated", org_id=str(org.id))
    return _config_to_response(config)


@router.delete(
    "",
    status_code=204,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def delete_alert_config(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the alert configuration entirely."""
    org, actor = org_actor
    snapshot = _audit_safe_config(org.alert_config)
    org.alert_config = None
    await db.flush()
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="alert_config.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="alert_config",
        details={"removed": snapshot},
    )
    await db.commit()
    log.info("alert_config.deleted", org_id=str(org.id))


def _build_test_incident(org_id: uuid.UUID) -> Incident:
    """Build a fake incident for test alerts."""
    incident = Incident(
        id=uuid.uuid4(),
        org_id=org_id,
        agent_id=uuid.uuid4(),
        title="[TEST] This is a test alert from Parry",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        created_at=datetime.now(UTC),
    )
    incident.detections = [
        Detection(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            detector="test",
            severity=Severity.HIGH,
            confidence=1.0,
            reason="This is a test",
            triggered=True,
        )
    ]
    return incident


@router.post(
    "/test",
    status_code=200,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def send_test_alert(
    channel: str = "slack",
    org: Org = Depends(get_current_org),
) -> dict[str, str]:
    """Send a test alert to the specified channel (slack | email)."""
    config = org.alert_config or {}
    test_incident = _build_test_incident(org.id)
    dashboard = settings.dashboard_url or None

    if channel == "slack":
        webhook_url = config.get("slack_webhook_url")
        if not webhook_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Slack webhook URL configured",
            )
        success = await send_slack_alert(webhook_url, test_incident, dashboard_url=dashboard)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send Slack test alert. Check the webhook URL.",
            )
        return {"status": "sent", "channel": "slack"}

    if channel == "email":
        emails = config.get("alert_emails") or []
        if not emails:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No email recipients configured",
            )
        success = await send_email_alert(emails, test_incident, dashboard_url=dashboard)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send email. Check SMTP configuration on the server.",
            )
        return {"status": "sent", "channel": "email"}

    if channel == "pagerduty":
        routing_key = config.get("pagerduty_routing_key")
        if not routing_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No PagerDuty routing key configured",
            )
        success = await send_pagerduty_alert(routing_key, test_incident, dashboard_url=dashboard)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send PagerDuty test alert. Check the routing key.",
            )
        return {"status": "sent", "channel": "pagerduty"}

    if channel == "opsgenie":
        api_key = config.get("opsgenie_api_key")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Opsgenie API key configured",
            )
        success = await send_opsgenie_alert(api_key, test_incident, dashboard_url=dashboard)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send Opsgenie test alert. Check the API key.",
            )
        return {"status": "sent", "channel": "opsgenie"}

    if channel == "webhook":
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No webhook URL configured",
            )
        webhook_headers = config.get("webhook_headers") or {}
        success = await send_webhook_alert(
            webhook_url, test_incident, dashboard_url=dashboard, headers=webhook_headers
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send webhook. Check the URL and that it accepts POST.",
            )
        return {"status": "sent", "channel": "webhook"}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="channel must be 'slack', 'email', 'webhook', 'pagerduty', or 'opsgenie'",
    )
