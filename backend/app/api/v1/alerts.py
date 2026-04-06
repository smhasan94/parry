"""Alert config API — manage Slack webhook and severity thresholds per org."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_org
from app.db.models import Detection, Incident, IncidentStatus, Org, Severity
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services.alert_service import send_email_alert, send_slack_alert

log = structlog.get_logger()

router = APIRouter()


class AlertConfigResponse(ParrySchema):
    slack_webhook_url: str | None = None
    alert_emails: list[str] = []
    min_severity: str = "high"
    enabled: bool = False


class AlertConfigUpdate(ParrySchema):
    slack_webhook_url: HttpUrl | None = None
    alert_emails: list[EmailStr] | None = None
    min_severity: str | None = None


def _config_to_response(config: dict | None) -> AlertConfigResponse:
    config = config or {}
    return AlertConfigResponse(
        slack_webhook_url=config.get("slack_webhook_url"),
        alert_emails=config.get("alert_emails") or [],
        min_severity=config.get("min_severity", "high"),
        enabled=bool(config.get("slack_webhook_url") or config.get("alert_emails")),
    )


@router.get("", response_model=AlertConfigResponse)
async def get_alert_config(
    org: Org = Depends(get_current_org),
) -> AlertConfigResponse:
    """Get the current alert configuration for the org."""
    return _config_to_response(org.alert_config)


@router.put("", response_model=AlertConfigResponse)
async def update_alert_config(
    body: AlertConfigUpdate,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> AlertConfigResponse:
    """Update the alert configuration for the org."""
    config = dict(org.alert_config or {})

    if body.slack_webhook_url is not None:
        config["slack_webhook_url"] = str(body.slack_webhook_url)

    if body.alert_emails is not None:
        config["alert_emails"] = [str(e) for e in body.alert_emails]

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
    await db.commit()
    log.info("alert_config.updated", org_id=str(org.id))
    return _config_to_response(config)


@router.delete("", status_code=204)
async def delete_alert_config(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the alert configuration entirely."""
    org.alert_config = None
    await db.flush()
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


@router.post("/test", status_code=200)
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

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="channel must be 'slack' or 'email'",
    )
