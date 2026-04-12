"""Slack Bot service — interactive incident triage.

Builds Block Kit messages with action buttons and handles interactive
payloads from Slack. Extends the existing slack_webhook_url integration
with richer formatting and interactive actions.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.core.metrics import record_alert_sent
from app.db.models import Incident, Severity

log = structlog.get_logger()

SEVERITY_EMOJI = {
    Severity.LOW: ":large_blue_circle:",
    Severity.MEDIUM: ":warning:",
    Severity.HIGH: ":rotating_light:",
    Severity.CRITICAL: ":fire:",
}

SEVERITY_COLOR = {
    Severity.LOW: "#3b82f6",
    Severity.MEDIUM: "#eab308",
    Severity.HIGH: "#f97316",
    Severity.CRITICAL: "#dc2626",
}


def build_block_kit_message(
    incident: Incident,
    dashboard_url: str | None = None,
) -> dict[str, Any]:
    """Build a Slack Block Kit message for incident triage."""
    sev = incident.severity
    emoji = SEVERITY_EMOJI.get(sev, ":grey_question:")
    color = SEVERITY_COLOR.get(sev, "#6b7280")
    incident_url = f"{dashboard_url.rstrip('/')}/incidents" if dashboard_url else None

    # Top detector info
    top_detector = ""
    if incident.detections:
        top = max(incident.detections, key=lambda d: d.confidence)
        top_detector = f"*Detector:* {top.detector} ({top.confidence * 100:.0f}% confidence)"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {incident.title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:* {sev.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Status:* {incident.status.value}"},
                {"type": "mrkdwn", "text": f"*Agent:* `{incident.agent_id}`"},
                {"type": "mrkdwn", "text": top_detector or "*Detector:* —"},
            ],
        },
    ]

    # Detection details
    if incident.detections and len(incident.detections) > 1:
        det_lines = []
        for d in sorted(incident.detections, key=lambda x: x.confidence, reverse=True)[:5]:
            det_lines.append(f"  {d.detector}: _{d.reason}_ ({d.confidence * 100:.0f}%)")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Detections:*\n" + "\n".join(det_lines),
            },
        })

    # Action buttons
    actions: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Acknowledge", "emoji": True},
            "style": "primary",
            "action_id": "parry_acknowledge",
            "value": str(incident.id),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Escalate", "emoji": True},
            "style": "danger",
            "action_id": "parry_escalate",
            "value": str(incident.id),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Snooze 1h", "emoji": True},
            "action_id": "parry_snooze",
            "value": str(incident.id),
        },
    ]

    if incident_url:
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "View in Dashboard", "emoji": True},
            "url": incident_url,
            "action_id": "parry_view_dashboard",
        })

    blocks.append({"type": "actions", "elements": actions})

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Incident `{str(incident.id)[:8]}` · {incident.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
            },
        ],
    })

    return {
        "blocks": blocks,
        "attachments": [{"color": color, "blocks": []}],
    }


def build_action_response(
    action_id: str,
    incident_id: str,
    user_name: str,
) -> dict[str, Any]:
    """Build a Slack response message for an interactive action."""
    action_labels = {
        "parry_acknowledge": f":white_check_mark: *{user_name}* acknowledged incident `{incident_id[:8]}`",
        "parry_escalate": f":rotating_light: *{user_name}* escalated incident `{incident_id[:8]}`",
        "parry_snooze": f":zzz: *{user_name}* snoozed incident `{incident_id[:8]}` for 1 hour",
    }

    text = action_labels.get(action_id, f"*{user_name}* took action on `{incident_id[:8]}`")

    return {
        "response_type": "in_channel",
        "replace_original": False,
        "text": text,
    }


async def send_block_kit_message(
    webhook_url: str,
    incident: Incident,
    dashboard_url: str | None = None,
) -> bool:
    """Send a Block Kit message to Slack via incoming webhook."""
    payload = build_block_kit_message(incident, dashboard_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        log.info(
            "slack_bot.message_sent",
            incident_id=str(incident.id),
            severity=incident.severity.value,
        )
        record_alert_sent(channel="slack_bot", success=True)
        return True
    except httpx.HTTPError as e:
        log.warning(
            "slack_bot.send_failed",
            incident_id=str(incident.id),
            error=str(e),
        )
        record_alert_sent(channel="slack_bot", success=False)
        return False
