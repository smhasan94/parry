"""Shareable incident report service.

Generates a self-contained report for an incident that can be shared
via a public link or exported as HTML. Designed for non-technical
stakeholders — clear language, timeline, detections, recommendations.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.core.config import settings


def generate_share_token(incident_id: str) -> str:
    """Generate a deterministic, tamper-proof share token for an incident.

    Uses HMAC-SHA256 with the app secret so tokens can be verified
    without a database lookup.
    """
    secret = (settings.app_secret_key or "parry-dev-secret").encode()
    return hmac.new(secret, incident_id.encode(), hashlib.sha256).hexdigest()[:24]


def verify_share_token(incident_id: str, token: str) -> bool:
    """Verify a share token is valid for the given incident."""
    expected = generate_share_token(incident_id)
    return hmac.compare_digest(expected, token)


def build_share_report(
    incident: dict[str, Any],
    detections: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a shareable report data structure.

    Pure function — takes pre-fetched data, returns report dict.
    """
    # Generate recommendations based on detections
    recommendations = _generate_recommendations(detections)

    # Timeline entries
    timeline = []
    for event in events:
        entry: dict[str, Any] = {
            "timestamp": event.get("timestamp"),
            "type": "event",
            "summary": _summarize_event(event),
        }
        # Mark events that triggered detections
        event_detections = [
            d for d in detections
            if d.get("event_id") == event.get("id")
        ]
        if event_detections:
            entry["detections"] = event_detections
            entry["type"] = "detection"
        timeline.append(entry)

    return {
        "incident": {
            "id": incident.get("id"),
            "title": incident.get("title"),
            "severity": incident.get("severity"),
            "status": incident.get("status"),
            "created_at": incident.get("created_at"),
        },
        "summary": _generate_summary(incident, detections),
        "timeline": timeline,
        "detections": detections,
        "recommendations": recommendations,
    }


def _summarize_event(event: dict[str, Any]) -> str:
    """Create a one-line summary of an event."""
    model = event.get("model", "unknown model")
    tools = event.get("tool_calls") or []
    tool_count = len(tools)
    if tool_count > 0:
        tool_names = [t.get("name", "tool") for t in tools[:3]]
        return f"LLM call ({model}) with {tool_count} tool call(s): {', '.join(tool_names)}"
    return f"LLM call ({model})"


def _generate_summary(
    incident: dict[str, Any],
    detections: list[dict[str, Any]],
) -> str:
    """Generate a plain-English summary of what happened."""
    severity = incident.get("severity", "unknown")
    title = incident.get("title", "Security incident")
    det_count = len(detections)
    det_types = list({d.get("detector", "unknown") for d in detections})

    parts = [f"{title}."]
    parts.append(f"Severity: {severity.upper()}.")
    parts.append(f"{det_count} detection(s) triggered by: {', '.join(det_types)}.")

    return " ".join(parts)


def _generate_recommendations(detections: list[dict[str, Any]]) -> list[str]:
    """Generate actionable recommendations based on detection types."""
    recs = []
    det_types = {d.get("detector") for d in detections}

    if "prompt_injection" in det_types:
        recs.append(
            "Review and strengthen system prompt boundaries."
            " Consider adding explicit instruction anchoring."
        )
    if "jailbreak" in det_types:
        recs.append(
            "Audit agent permissions and ensure the model cannot be coerced"
            " into bypassing safety controls."
        )
    if "data_exfiltration" in det_types:
        recs.append(
            "Review response content filtering."
            " Ensure PII and credentials are stripped before reaching the user."
        )
    if "privilege_escalation" in det_types:
        recs.append(
            "Restrict agent tool permissions to minimum required scope."
            " Enable enforcing mode on permission boundaries."
        )
    if "tool_misuse" in det_types:
        recs.append(
            "Update tool allowlists and blocklists in the agent's policy."
            " Consider enabling blocking mode."
        )

    if not recs:
        recs.append("Review the detection details above and adjust detector thresholds if needed.")

    return recs


def render_share_html(report: dict[str, Any]) -> str:
    """Render the share report as a standalone HTML page."""
    inc = report["incident"]
    severity_colors = {
        "critical": "#dc2626",
        "high": "#f97316",
        "medium": "#eab308",
        "low": "#3b82f6",
    }
    color = severity_colors.get(inc.get("severity", ""), "#6b7280")

    timeline_html = ""
    for entry in report["timeline"]:
        marker = "&#128308;" if entry["type"] == "detection" else "&#9679;"
        ts = entry.get("timestamp", "")
        timeline_html += (
            f"<div style='padding:8px 0;border-bottom:1px solid #334155'>"
            f"{marker} <span style='color:#94a3b8'>{ts}</span> — {entry['summary']}</div>"
        )

    recs_html = "".join(f"<li style='margin:4px 0'>{r}</li>" for r in report["recommendations"])

    title = inc.get("title", "Parry")
    sev_line = (
        f"{inc.get('severity', '').upper()} &middot;"
        f" {inc.get('status', '')} &middot; {inc.get('created_at', '')}"
    )
    body_style = (
        "font-family:system-ui,sans-serif;color:#e2e8f0;background:#0f172a;"
        "padding:32px;max-width:720px;margin:0 auto"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Incident Report — {title}</title></head>
<body style="{body_style}">
<div style="display:flex;align-items:center;gap:12px;margin-bottom:24px">
<div style="width:12px;height:12px;border-radius:50%;background:{color}"></div>
<h1 style="margin:0;color:#f8fafc;font-size:22px">{inc.get('title', 'Security Incident')}</h1>
</div>
<p style="color:#94a3b8;font-size:14px">{sev_line}</p>

<h2 style="color:#f8fafc;font-size:16px;margin-top:32px">Summary</h2>
<p style="font-size:14px;line-height:1.6">{report['summary']}</p>

<h2 style="color:#f8fafc;font-size:16px;margin-top:32px">Timeline</h2>
{timeline_html or '<p style="color:#64748b">No events recorded.</p>'}

<h2 style="color:#f8fafc;font-size:16px;margin-top:32px">Recommendations</h2>
<ul style="font-size:14px;line-height:1.6;padding-left:20px">{recs_html}</ul>

<hr style="border:1px solid #334155;margin:32px 0">
<p style="color:#64748b;font-size:12px">Generated by Parry &mdash; AI Agent Runtime Security</p>
</body></html>"""
