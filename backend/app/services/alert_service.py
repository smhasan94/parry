"""Alert service — sends incident notifications to configured channels."""
import httpx
import structlog

from app.db.models import Incident, Org, Severity

log = structlog.get_logger()

SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

SEVERITY_COLOR = {
    Severity.LOW: "#3b82f6",  # blue
    Severity.MEDIUM: "#eab308",  # yellow
    Severity.HIGH: "#f97316",  # orange
    Severity.CRITICAL: "#dc2626",  # red
}

SEVERITY_EMOJI = {
    Severity.LOW: ":information_source:",
    Severity.MEDIUM: ":warning:",
    Severity.HIGH: ":rotating_light:",
    Severity.CRITICAL: ":fire:",
}


def should_alert(org: Org, severity: Severity) -> bool:
    """Return True if the org's alert config wants to be notified at this severity."""
    config = org.alert_config or {}
    if not config.get("slack_webhook_url"):
        return False
    min_severity_str = config.get("min_severity", "high")
    try:
        min_severity = Severity(min_severity_str)
    except ValueError:
        min_severity = Severity.HIGH
    return SEVERITY_RANK[severity] >= SEVERITY_RANK[min_severity]


def build_slack_payload(incident: Incident, dashboard_url: str | None = None) -> dict:
    """Build a Slack message payload for an incident."""
    severity = incident.severity
    emoji = SEVERITY_EMOJI[severity]
    color = SEVERITY_COLOR[severity]

    fields = [
        {"title": "Severity", "value": severity.value.upper(), "short": True},
        {"title": "Status", "value": incident.status.value, "short": True},
    ]
    if incident.detections:
        top = max(incident.detections, key=lambda d: d.confidence)
        fields.append(
            {
                "title": "Top Detector",
                "value": f"{top.detector} ({top.confidence * 100:.0f}% confidence)",
                "short": False,
            }
        )

    attachment: dict = {
        "color": color,
        "title": f"{emoji} {incident.title}",
        "fields": fields,
        "ts": int(incident.created_at.timestamp()),
    }
    if dashboard_url:
        attachment["title_link"] = f"{dashboard_url.rstrip('/')}/incidents"

    return {
        "text": f"New {severity.value} incident: {incident.title}",
        "attachments": [attachment],
    }


async def send_slack_alert(
    webhook_url: str, incident: Incident, dashboard_url: str | None = None
) -> bool:
    """POST the incident to a Slack incoming webhook. Returns True on success."""
    payload = build_slack_payload(incident, dashboard_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        log.info(
            "alert.slack_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
        )
        return True
    except httpx.HTTPError as e:
        log.warning(
            "alert.slack_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        return False


async def dispatch_incident_alert(
    org: Org, incident: Incident, dashboard_url: str | None = None
) -> None:
    """Send alerts for an incident to all configured channels for the org."""
    if not should_alert(org, incident.severity):
        return

    config = org.alert_config or {}
    webhook_url = config.get("slack_webhook_url")
    if webhook_url:
        await send_slack_alert(webhook_url, incident, dashboard_url)
