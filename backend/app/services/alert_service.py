"""Alert service — sends incident notifications to configured channels."""
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import structlog

from app.core.config import settings
from app.core.metrics import record_alert_sent
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


def _meets_min_severity(config: dict, severity: Severity) -> bool:
    min_severity_str = config.get("min_severity", "high")
    try:
        min_severity = Severity(min_severity_str)
    except ValueError:
        min_severity = Severity.HIGH
    return SEVERITY_RANK[severity] >= SEVERITY_RANK[min_severity]


def should_alert(org: Org, severity: Severity) -> bool:
    """Return True if the org's alert config wants to be notified at this severity.

    Considers any configured channel (Slack webhook OR alert_emails).
    """
    config = org.alert_config or {}
    has_channel = bool(config.get("slack_webhook_url") or config.get("alert_emails"))
    if not has_channel:
        return False
    return _meets_min_severity(config, severity)


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
        record_alert_sent(channel="slack", success=True)
        return True
    except httpx.HTTPError as e:
        log.warning(
            "alert.slack_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="slack", success=False)
        return False


def build_email_subject(incident: Incident) -> str:
    return f"[Parry] {incident.severity.value.upper()} incident: {incident.title}"


def build_email_html(incident: Incident, dashboard_url: str | None = None) -> str:
    """Build a simple HTML email body for an incident."""
    color = SEVERITY_COLOR[incident.severity]
    severity_label = incident.severity.value.upper()

    detection_rows = ""
    if incident.detections:
        for d in sorted(incident.detections, key=lambda x: x.confidence, reverse=True):
            detection_rows += (
                f"<tr>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{d.detector}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{d.reason}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>"
                f"{d.confidence * 100:.0f}%</td>"
                f"</tr>"
            )

    link_html = ""
    if dashboard_url:
        url = f"{dashboard_url.rstrip('/')}/incidents"
        link_html = (
            f"<p style='margin-top:24px'>"
            f"<a href='{url}' style='background:{color};color:white;padding:10px 20px;"
            f"border-radius:6px;text-decoration:none;display:inline-block'>"
            f"View in Dashboard</a></p>"
        )

    return f"""\
<html>
  <body style='font-family:-apple-system,sans-serif;color:#222;max-width:600px;margin:auto'>
    <div style='border-left:4px solid {color};padding-left:16px;margin:24px 0'>
      <p style='color:{color};font-weight:bold;margin:0;text-transform:uppercase;font-size:12px'>
        {severity_label} severity
      </p>
      <h2 style='margin:8px 0'>{incident.title}</h2>
      <p style='color:#666;margin:0'>Status: {incident.status.value}</p>
    </div>
    {"<table style='width:100%;border-collapse:collapse;font-size:14px'>"
     "<thead><tr style='background:#f5f5f5'>"
     "<th style='padding:6px 12px;text-align:left'>Detector</th>"
     "<th style='padding:6px 12px;text-align:left'>Reason</th>"
     "<th style='padding:6px 12px;text-align:right'>Confidence</th>"
     "</tr></thead><tbody>" + detection_rows + "</tbody></table>"
     if detection_rows else ""}
    {link_html}
    <p style='color:#999;font-size:12px;margin-top:32px'>
      You're receiving this because email alerts are enabled for your Parry organization.
    </p>
  </body>
</html>"""


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send_email_sync(to_addresses: list[str], subject: str, html_body: str) -> None:
    """Synchronous SMTP send. Called via run_in_executor from async code."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(settings.smtp_from, to_addresses, msg.as_string())


async def send_email_alert(
    to_addresses: list[str], incident: Incident, dashboard_url: str | None = None
) -> bool:
    """Send an email alert via SMTP. Returns True on success."""
    if not _smtp_configured():
        log.warning("alert.email_skipped", reason="SMTP not configured")
        return False
    if not to_addresses:
        return False

    subject = build_email_subject(incident)
    html = build_email_html(incident, dashboard_url)

    try:
        await asyncio.get_running_loop().run_in_executor(
            None, _send_email_sync, to_addresses, subject, html
        )
        log.info(
            "alert.email_sent",
            incident_id=str(incident.id),
            recipients=len(to_addresses),
        )
        record_alert_sent(channel="email", success=True)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.warning(
            "alert.email_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="email", success=False)
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

    alert_emails = config.get("alert_emails") or []
    if alert_emails:
        await send_email_alert(alert_emails, incident, dashboard_url)
