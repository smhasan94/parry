"""Weekly security digest service.

Assembles a summary of the past 7 days for an org: fleet health
trends, top incidents, detection coverage, and agents needing attention.
Used by the weekly Celery task and the digest preview API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


def compute_digest(
    *,
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events_7d: int,
    events_prev_7d: int,
    detections_7d: int,
    detections_prev_7d: int,
) -> dict[str, Any]:
    """Build the digest data structure from pre-fetched data.

    This is a pure function so it can be tested without a database.
    """
    now = datetime.now(UTC)
    period_start = now - timedelta(days=7)

    # Fleet health summary
    total_agents = len(agents)
    healthy = sum(1 for a in agents if (a.get("health_grade") or "F") in ("A", "B"))
    degraded = sum(1 for a in agents if (a.get("health_grade") or "F") in ("C", "D"))
    critical = sum(1 for a in agents if (a.get("health_grade") or "F") == "F")

    # Event volume trend
    event_delta = events_7d - events_prev_7d
    event_trend = "up" if event_delta > 0 else "down" if event_delta < 0 else "flat"
    event_pct = round(abs(event_delta) / max(events_prev_7d, 1) * 100)

    # Detection volume trend
    det_delta = detections_7d - detections_prev_7d
    det_trend = "up" if det_delta > 0 else "down" if det_delta < 0 else "flat"
    det_pct = round(abs(det_delta) / max(detections_prev_7d, 1) * 100)

    # Top incidents (by severity, then recency)
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    sorted_incidents = sorted(
        incidents,
        key=lambda i: (severity_rank.get(i.get("severity", "low"), 0), i.get("created_at", "")),
        reverse=True,
    )
    top_incidents = sorted_incidents[:5]

    # Agents needing attention (grade D or F)
    attention_agents = [
        {"id": a["id"], "name": a["name"], "grade": a.get("health_grade", "?")}
        for a in agents
        if (a.get("health_grade") or "F") in ("D", "F")
    ]

    return {
        "period_start": period_start.isoformat(),
        "period_end": now.isoformat(),
        "fleet": {
            "total": total_agents,
            "healthy": healthy,
            "degraded": degraded,
            "critical": critical,
        },
        "events": {
            "count_7d": events_7d,
            "count_prev_7d": events_prev_7d,
            "trend": event_trend,
            "change_pct": event_pct,
        },
        "detections": {
            "count_7d": detections_7d,
            "count_prev_7d": detections_prev_7d,
            "trend": det_trend,
            "change_pct": det_pct,
        },
        "top_incidents": top_incidents,
        "attention_agents": attention_agents,
    }


def render_digest_html(digest: dict[str, Any], org_name: str = "Your Org") -> str:
    """Render the digest as a simple HTML email."""
    fleet = digest["fleet"]
    events = digest["events"]
    dets = digest["detections"]
    def _trend_arrow(trend: str) -> str:
        if trend == "up":
            return "&#9650;"
        if trend == "down":
            return "&#9660;"
        return "&#8212;"

    ev_arrow = _trend_arrow(events["trend"])
    det_arrow = _trend_arrow(dets["trend"])

    incident_rows = ""
    for inc in digest["top_incidents"]:
        sev = inc.get("severity", "low").upper()
        title = inc.get("title", "Untitled")
        incident_rows += (
            f"<tr><td style='padding:4px 8px'>{sev}</td>"
            f"<td style='padding:4px 8px'>{title}</td></tr>"
        )

    attention_rows = ""
    for ag in digest["attention_agents"]:
        attention_rows += (
            f"<tr><td style='padding:4px 8px'>{ag['name']}</td>"
            f"<td style='padding:4px 8px'>Grade {ag['grade']}</td></tr>"
        )

    _h2 = "color:#f8fafc;font-size:16px;margin-top:24px"
    incidents_section = (
        f'<h2 style="{_h2}">Top Incidents</h2>'
        f'<table style="font-size:14px">{incident_rows}</table>'
        if incident_rows
        else ""
    )
    attention_section = (
        f'<h2 style="{_h2}">Agents Needing Attention</h2>'
        f'<table style="font-size:14px">{attention_rows}</table>'
        if attention_rows
        else ""
    )
    period = f"{digest['period_start'][:10]} to {digest['period_end'][:10]}"
    ev_line = (
        f"Events: <b>{events['count_7d']}</b> {ev_arrow} {events['change_pct']}% vs prior week"
    )
    det_line = (
        f"Detections: <b>{dets['count_7d']}</b> {det_arrow} {dets['change_pct']}% vs prior week"
    )
    _p = "padding:2px 12px"
    fleet_rows = (
        f"<tr><td style='{_p}'>Total agents</td><td><b>{fleet['total']}</b></td></tr>\n"
        f"<tr><td style='{_p};color:#22c55e'>Healthy (A/B)</td>"
        f"<td><b>{fleet['healthy']}</b></td></tr>\n"
        f"<tr><td style='{_p};color:#eab308'>Degraded (C/D)</td>"
        f"<td><b>{fleet['degraded']}</b></td></tr>\n"
        f"<tr><td style='{_p};color:#ef4444'>Critical (F)</td>"
        f"<td><b>{fleet['critical']}</b></td></tr>"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:system-ui,sans-serif;color:#e2e8f0;background:#0f172a;padding:24px">
<h1 style="color:#f8fafc;font-size:20px">Parry Weekly Digest &mdash; {org_name}</h1>
<p style="color:#94a3b8;font-size:14px">{period}</p>

<h2 style="{_h2}">Fleet Health</h2>
<table style="font-size:14px">
{fleet_rows}
</table>

<h2 style="{_h2}">Activity</h2>
<p style="font-size:14px">{ev_line}</p>
<p style="font-size:14px">{det_line}</p>

{incidents_section}

{attention_section}

<hr style="border:1px solid #334155;margin:24px 0">
<p style="color:#64748b;font-size:12px">Parry &mdash; AI Agent Runtime Security</p>
</body></html>"""
