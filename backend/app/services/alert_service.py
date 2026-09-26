"""Alert service — sends incident notifications to configured channels."""

import asyncio
import smtplib
import uuid
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.core.metrics import record_alert_sent
from app.core.url_safety import UnsafeURLError, assert_public_https_url
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


def build_webhook_payload(incident: Incident, dashboard_url: str | None = None) -> dict[str, Any]:
    """Build a generic JSON payload for arbitrary webhook receivers.

    Designed to be consumable by PagerDuty, Opsgenie, Teams, Discord, n8n,
    Zapier, custom services, etc. Stable schema versioned via `schema_version`.
    """
    detections_payload: list[dict[str, Any]] = []
    if incident.detections:
        for d in sorted(incident.detections, key=lambda x: x.confidence, reverse=True):
            detections_payload.append(
                {
                    "detector": d.detector,
                    "severity": d.severity.value,
                    "confidence": d.confidence,
                    "reason": d.reason,
                }
            )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event": "incident.created",
        "incident": {
            "id": str(incident.id),
            "title": incident.title,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "agent_id": str(incident.agent_id),
            "org_id": str(incident.org_id),
            "created_at": incident.created_at.isoformat(),
            "detections": detections_payload,
        },
    }
    if dashboard_url:
        payload["incident"]["dashboard_url"] = f"{dashboard_url.rstrip('/')}/incidents"
    return payload


def _meets_min_severity(config: dict[str, Any], severity: Severity) -> bool:
    min_severity_str = config.get("min_severity", "high")
    try:
        min_severity = Severity(min_severity_str)
    except ValueError:
        min_severity = Severity.HIGH
    return SEVERITY_RANK[severity] >= SEVERITY_RANK[min_severity]


def should_alert(org: Org, severity: Severity) -> bool:
    """Return True if the org's alert config wants to be notified at this severity.

    Considers any configured channel (Slack, email, or generic webhook).
    """
    config = org.alert_config or {}
    has_channel = bool(
        config.get("slack_webhook_url")
        or config.get("alert_emails")
        or config.get("webhook_url")
        or config.get("pagerduty_routing_key")
        or config.get("opsgenie_api_key")
    )
    if not has_channel:
        return False
    return _meets_min_severity(config, severity)


def build_slack_payload(incident: Incident, dashboard_url: str | None = None) -> dict[str, Any]:
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

    attachment: dict[str, Any] = {
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
        assert_public_https_url(webhook_url)
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
    except (httpx.HTTPError, UnsafeURLError) as e:
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
    {
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<thead><tr style='background:#f5f5f5'>"
        "<th style='padding:6px 12px;text-align:left'>Detector</th>"
        "<th style='padding:6px 12px;text-align:left'>Reason</th>"
        "<th style='padding:6px 12px;text-align:right'>Confidence</th>"
        "</tr></thead><tbody>" + detection_rows + "</tbody></table>"
        if detection_rows
        else ""
    }
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


PAGERDUTY_SEVERITY = {
    Severity.CRITICAL: "critical",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "info",
}

OPSGENIE_PRIORITY = {
    Severity.CRITICAL: "P1",
    Severity.HIGH: "P2",
    Severity.MEDIUM: "P3",
    Severity.LOW: "P5",
}


def build_pagerduty_payload(
    incident: Incident, routing_key: str, dashboard_url: str | None = None
) -> dict[str, Any]:
    """Build a PagerDuty Events API v2 payload.

    Uses the incident id as the dedup key so PagerDuty collapses
    retriggers into a single open alert (idempotent on our side).
    """
    custom: dict[str, Any] = {
        "incident_id": str(incident.id),
        "agent_id": str(incident.agent_id),
        "org_id": str(incident.org_id),
    }
    if dashboard_url:
        custom["dashboard_url"] = f"{dashboard_url.rstrip('/')}/incidents"
    if incident.detections:
        top = max(incident.detections, key=lambda d: d.confidence)
        custom["top_detector"] = top.detector
        custom["top_reason"] = top.reason

    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"parry-incident-{incident.id}",
        "payload": {
            "summary": incident.title,
            "severity": PAGERDUTY_SEVERITY[incident.severity],
            "source": "Parry AI Security",
            "custom_details": custom,
        },
    }


async def send_pagerduty_alert(
    routing_key: str, incident: Incident, dashboard_url: str | None = None
) -> bool:
    """POST the incident to PagerDuty's Events API v2.

    Returns True on success. PagerDuty's sink-side severity mapping is
    narrower than our Severity enum, so callers should still gate on
    ``_meets_min_severity``.
    """
    payload = build_pagerduty_payload(incident, routing_key, dashboard_url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://events.pagerduty.com/v2/enqueue", json=payload)
            resp.raise_for_status()
        log.info(
            "alert.pagerduty_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
        )
        record_alert_sent(channel="pagerduty", success=True)
        return True
    except httpx.HTTPError as e:
        log.warning(
            "alert.pagerduty_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="pagerduty", success=False)
        return False


def build_opsgenie_payload(incident: Incident, dashboard_url: str | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {
        "incident_id": str(incident.id),
        "agent_id": str(incident.agent_id),
        "org_id": str(incident.org_id),
    }
    if dashboard_url:
        details["dashboard_url"] = f"{dashboard_url.rstrip('/')}/incidents"

    return {
        "message": incident.title,
        "alias": f"parry-{incident.id}",
        "priority": OPSGENIE_PRIORITY[incident.severity],
        "source": "Parry",
        "tags": ["parry", "ai-security", incident.severity.value],
        "details": details,
    }


async def send_opsgenie_alert(
    api_key: str, incident: Incident, dashboard_url: str | None = None
) -> bool:
    """POST the incident to Opsgenie's Alerts API. Returns True on success."""
    payload = build_opsgenie_payload(incident, dashboard_url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.opsgenie.com/v2/alerts",
                json=payload,
                headers={"Authorization": f"GenieKey {api_key}"},
            )
            resp.raise_for_status()
        log.info(
            "alert.opsgenie_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
        )
        record_alert_sent(channel="opsgenie", success=True)
        return True
    except httpx.HTTPError as e:
        log.warning(
            "alert.opsgenie_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="opsgenie", success=False)
        return False


async def send_webhook_alert(
    webhook_url: str,
    incident: Incident,
    dashboard_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    """POST a generic JSON payload to an arbitrary webhook URL."""
    payload = build_webhook_payload(incident, dashboard_url)
    try:
        assert_public_https_url(webhook_url)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers or {})
            resp.raise_for_status()
        log.info(
            "alert.webhook_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
            status=resp.status_code,
        )
        record_alert_sent(channel="webhook", success=True)
        return True
    except (httpx.HTTPError, UnsafeURLError) as e:
        log.warning(
            "alert.webhook_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="webhook", success=False)
        return False


async def dispatch_incident_alert(
    org: Org, incident: Incident, dashboard_url: str | None = None
) -> None:
    """Send alerts for an incident to all configured channels for the org."""
    if not should_alert(org, incident.severity):
        return

    config = org.alert_config or {}

    slack_url = config.get("slack_webhook_url")
    if slack_url:
        await send_slack_alert(slack_url, incident, dashboard_url)

    alert_emails = config.get("alert_emails") or []
    if alert_emails:
        await send_email_alert(alert_emails, incident, dashboard_url)

    webhook_url = config.get("webhook_url")
    if webhook_url:
        webhook_headers = config.get("webhook_headers") or {}
        await send_webhook_alert(webhook_url, incident, dashboard_url, headers=webhook_headers)

    pagerduty_key = config.get("pagerduty_routing_key")
    if pagerduty_key:
        await send_pagerduty_alert(pagerduty_key, incident, dashboard_url)

    opsgenie_key = config.get("opsgenie_api_key")
    if opsgenie_key:
        await send_opsgenie_alert(opsgenie_key, incident, dashboard_url)


# ── Budget threshold alerts ──────────────────────────────────────


@dataclass
class BudgetAlertContext:
    """Data needed to compose a budget threshold alert message."""

    budget_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    org_id: uuid.UUID
    period: str
    cap_usd: float
    current_spend: float
    threshold_pct: int


def _build_budget_alert_message(ctx: BudgetAlertContext) -> str:
    pct_used = (ctx.current_spend / ctx.cap_usd) * 100 if ctx.cap_usd else 0.0
    return (
        f"Budget alert for agent '{ctx.agent_name}' ({ctx.agent_id}): "
        f"${ctx.current_spend:.4f} of ${ctx.cap_usd:.2f} {ctx.period} cap used "
        f"({pct_used:.1f}%) — crossed {ctx.threshold_pct}% threshold."
    )


def _build_budget_slack_payload(ctx: BudgetAlertContext) -> dict[str, Any]:
    pct_used = (ctx.current_spend / ctx.cap_usd) * 100 if ctx.cap_usd else 0.0
    color = "#eab308" if ctx.threshold_pct < 90 else "#dc2626"
    message = _build_budget_alert_message(ctx)
    return {
        "text": message,
        "attachments": [
            {
                "color": color,
                "title": f":warning: Budget threshold crossed: {ctx.threshold_pct}%",
                "fields": [
                    {"title": "Agent", "value": ctx.agent_name, "short": True},
                    {"title": "Period", "value": ctx.period, "short": True},
                    {
                        "title": "Spend",
                        "value": f"${ctx.current_spend:.4f} / ${ctx.cap_usd:.2f}",
                        "short": True,
                    },
                    {"title": "Usage", "value": f"{pct_used:.1f}%", "short": True},
                ],
            }
        ],
    }


def _build_budget_webhook_payload(ctx: BudgetAlertContext) -> dict[str, Any]:
    pct_used = (ctx.current_spend / ctx.cap_usd) * 100 if ctx.cap_usd else 0.0
    return {
        "schema_version": "1.0",
        "event": "budget.threshold_crossed",
        "budget": {
            "id": str(ctx.budget_id),
            "agent_id": str(ctx.agent_id),
            "agent_name": ctx.agent_name,
            "org_id": str(ctx.org_id),
            "period": ctx.period,
            "cap_usd": ctx.cap_usd,
            "current_spend": ctx.current_spend,
            "pct_used": round(pct_used, 2),
            "threshold_pct": ctx.threshold_pct,
        },
    }


async def dispatch_budget_alert(org: Org, ctx: BudgetAlertContext) -> None:
    """Send budget threshold alerts to all configured channels for the org.

    Mirrors ``dispatch_incident_alert`` but accepts a BudgetAlertContext
    instead of an Incident so that budget events don't need to go through
    the incident pipeline.
    """
    config = org.alert_config or {}
    has_channel = bool(
        config.get("slack_webhook_url")
        or config.get("alert_emails")
        or config.get("webhook_url")
        or config.get("pagerduty_routing_key")
        or config.get("opsgenie_api_key")
    )
    if not has_channel:
        log.debug(
            "budget_alert.no_channel_configured",
            budget_id=str(ctx.budget_id),
            threshold_pct=ctx.threshold_pct,
        )
        return

    log.info(
        "budget_alert.dispatching",
        budget_id=str(ctx.budget_id),
        agent_id=str(ctx.agent_id),
        threshold_pct=ctx.threshold_pct,
        current_spend=ctx.current_spend,
        cap_usd=ctx.cap_usd,
    )

    slack_url = config.get("slack_webhook_url")
    if slack_url:
        payload = _build_budget_slack_payload(ctx)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(slack_url, json=payload)
                resp.raise_for_status()
            record_alert_sent(channel="slack", success=True)
        except httpx.HTTPError as e:
            log.warning("budget_alert.slack_failed", error=str(e))
            record_alert_sent(channel="slack", success=False)

    alert_emails = config.get("alert_emails") or []
    if alert_emails and _smtp_configured():
        subject = (
            f"[Parry] Budget alert: {ctx.agent_name} crossed {ctx.threshold_pct}% of "
            f"${ctx.cap_usd:.2f} {ctx.period} cap"
        )
        html = (
            f"<html><body style='font-family:-apple-system,sans-serif'>"
            f"<h2>Budget Threshold Alert</h2>"
            f"<p>{_build_budget_alert_message(ctx)}</p>"
            f"<p style='color:#999;font-size:12px'>Parry AI Security</p>"
            f"</body></html>"
        )
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, _send_email_sync, alert_emails, subject, html
            )
            record_alert_sent(channel="email", success=True)
        except (smtplib.SMTPException, OSError) as e:
            log.warning("budget_alert.email_failed", error=str(e))
            record_alert_sent(channel="email", success=False)

    webhook_url = config.get("webhook_url")
    if webhook_url:
        payload = _build_budget_webhook_payload(ctx)
        webhook_headers: dict[str, str] = config.get("webhook_headers") or {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(webhook_url, json=payload, headers=webhook_headers)
                resp.raise_for_status()
            record_alert_sent(channel="webhook", success=True)
        except httpx.HTTPError as e:
            log.warning("budget_alert.webhook_failed", error=str(e))
            record_alert_sent(channel="webhook", success=False)
