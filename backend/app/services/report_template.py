"""Compliance report HTML template + WeasyPrint renderer.

Single-file inline CSS so WeasyPrint renders fully offline. No external
resources, no web fonts — uses system fonts (Liberation Sans in the
backend Docker image).
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def _fmt_day(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except ValueError:
        return iso


_STYLE = """
@page { size: Letter; margin: 0.75in; @bottom-center {
    content: "Parry Compliance Report — page " counter(page) " of " counter(pages);
    font-size: 9pt; color: #64748b;
} }
body { font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
       color: #0f172a; font-size: 10pt; line-height: 1.45; }
h1 { font-size: 28pt; margin: 0 0 0.25in 0; color: #0b1220; letter-spacing: -0.02em; }
h2 { font-size: 16pt; margin: 0.4in 0 0.15in 0; color: #0b1220;
     border-bottom: 2px solid #e2e8f0; padding-bottom: 6pt; }
h3 { font-size: 11pt; margin: 0.2in 0 0.08in 0; color: #334155; }
.cover { page-break-after: always; padding-top: 1.5in; }
.cover .brand { font-size: 12pt; letter-spacing: 0.2em;
                text-transform: uppercase; color: #475569; }
.cover .period { font-size: 14pt; color: #334155; margin-top: 0.3in; }
.cover .meta { margin-top: 1in; color: #64748b; font-size: 10pt; }
.cards { display: flex; gap: 10pt; margin: 0.15in 0 0.25in 0; }
.card { flex: 1; border: 1px solid #e2e8f0; border-radius: 6pt;
        padding: 10pt 12pt; background: #f8fafc; }
.card .label { font-size: 8pt; text-transform: uppercase;
               letter-spacing: 0.08em; color: #64748b; }
.card .value { font-size: 20pt; font-weight: 700; color: #0b1220; margin-top: 2pt; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; margin-top: 6pt; }
th { text-align: left; background: #f1f5f9; color: #334155;
     padding: 6pt 8pt; border-bottom: 1px solid #cbd5e1;
     font-weight: 600; text-transform: uppercase; font-size: 8pt;
     letter-spacing: 0.05em; }
td { padding: 6pt 8pt; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.sev-critical { color: #991b1b; font-weight: 600; }
.sev-high { color: #c2410c; font-weight: 600; }
.sev-medium { color: #a16207; }
.sev-low { color: #475569; }
.muted { color: #64748b; }
.footer-note { margin-top: 0.4in; font-size: 9pt; color: #64748b;
               border-top: 1px solid #e2e8f0; padding-top: 10pt; }
.policy-block { border: 1px solid #e2e8f0; border-radius: 4pt;
                padding: 8pt 10pt; margin-bottom: 8pt; background: #fafafa; }
.policy-block .name { font-weight: 600; color: #0b1220; }
.policy-block ul { margin: 4pt 0 0 16pt; padding: 0; }
.empty { color: #94a3b8; font-style: italic; }
"""


def _sev_class(sev: str) -> str:
    return f"sev-{sev.lower()}"


def _render_cards(summary: dict[str, Any]) -> str:
    cards = [
        ("Total Events", summary["total_events"]),
        ("Triggered Detections", summary["triggered_detections"]),
        ("Incidents", summary["total_incidents"]),
        ("Agents Monitored", summary["agents_monitored"]),
    ]
    return (
        '<div class="cards">'
        + "".join(
            f'<div class="card"><div class="label">{escape(label)}</div>'
            f'<div class="value">{value}</div></div>'
            for label, value in cards
        )
        + "</div>"
    )


def _render_severity_table(by_sev: dict[str, int]) -> str:
    order = ["critical", "high", "medium", "low"]
    rows = "".join(
        f'<tr><td class="{_sev_class(s)}">{escape(s.title())}</td>'
        f"<td>{by_sev.get(s, 0)}</td></tr>"
        for s in order
    )
    return (
        "<table><thead><tr><th>Severity</th><th>Triggered Count</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_detector_table(by_det: dict[str, int]) -> str:
    if not by_det:
        return '<p class="empty">No triggered detections in this period.</p>'
    rows = "".join(
        f"<tr><td>{escape(det)}</td><td>{count}</td></tr>"
        for det, count in sorted(by_det.items(), key=lambda kv: -kv[1])
    )
    return (
        "<table><thead><tr><th>Detector</th><th>Triggered Count</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_incident_table(incidents: list[dict[str, Any]]) -> str:
    if not incidents:
        return '<p class="empty">No incidents recorded in this period.</p>'
    rows = "".join(
        f"<tr>"
        f"<td>{_fmt_date(inc.get('created_at'))}</td>"
        f'<td>{escape(inc.get("title") or "")}</td>'
        f'<td class="{_sev_class(inc.get("severity", "low"))}">'
        f'{escape(str(inc.get("severity", "")).title())}</td>'
        f'<td>{escape(str(inc.get("status", "")).title())}</td>'
        f"<td>{_fmt_date(inc.get('resolved_at'))}</td>"
        f"</tr>"
        for inc in incidents
    )
    return (
        "<table><thead><tr><th>Created</th><th>Title</th><th>Severity</th>"
        "<th>Status</th><th>Resolved</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _render_policies(policies: list[dict[str, Any]]) -> str:
    if not policies:
        return '<p class="empty">No policies configured.</p>'
    blocks: list[str] = []
    for p in policies:
        parts = [f'<div class="name">{escape(p["name"])}</div>']
        items = []
        if p.get("allowed_tools"):
            items.append(f"<li>Allowed tools: {escape(', '.join(p['allowed_tools']))}</li>")
        if p.get("blocked_tools"):
            items.append(f"<li>Blocked tools: {escape(', '.join(p['blocked_tools']))}</li>")
        if p.get("allowed_domains"):
            items.append(
                f"<li>Allowed domains: {escape(', '.join(p['allowed_domains']))}</li>"
            )
        if p.get("blocked_domains"):
            items.append(
                f"<li>Blocked domains: {escape(', '.join(p['blocked_domains']))}</li>"
            )
        if p.get("max_token_budget"):
            items.append(f"<li>Max token budget: {p['max_token_budget']}</li>")
        if p.get("forbidden_patterns"):
            items.append(
                f"<li>Forbidden patterns: {len(p['forbidden_patterns'])} configured</li>"
            )
        if not items:
            items.append('<li class="muted">No rules configured.</li>')
        parts.append("<ul>" + "".join(items) + "</ul>")
        blocks.append(f'<div class="policy-block">{"".join(parts)}</div>')
    return "".join(blocks)


def _render_agent_table(agents: list[dict[str, Any]]) -> str:
    if not agents:
        return '<p class="empty">No agents registered.</p>'
    rows = "".join(
        f"<tr>"
        f'<td>{escape(a["name"])}</td>'
        f'<td>{"Active" if a.get("is_active") else "Inactive"}</td>'
        f'<td>{a.get("event_count", 0)}</td>'
        f'<td>{a.get("incident_count", 0)}</td>'
        f"</tr>"
        for a in agents
    )
    return (
        "<table><thead><tr><th>Agent</th><th>Status</th><th>Events</th>"
        "<th>Incidents</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def render_report_html(data: dict[str, Any]) -> str:
    """Render the compliance report data into a standalone HTML document."""
    org = data["org"]
    period = data["period"]
    summary = data["summary"]

    cover = f"""
    <section class="cover">
      <div class="brand">Parry — AI Agent Runtime Security</div>
      <h1>Compliance Report</h1>
      <div class="period">
        {escape(org['name'])}<br/>
        Period: {_fmt_day(period['start'])} → {_fmt_day(period['end'])}
      </div>
      <div class="meta">
        Generated {_fmt_date(data['generated_at'])}<br/>
        Organization ID: {escape(org['id'])}
      </div>
    </section>
    """

    body = f"""
    <h2>Executive Summary</h2>
    {_render_cards(summary)}
    <p class="muted">
      Total detections evaluated: {summary['total_detections']}
      ({summary['triggered_detections']} triggered).
    </p>

    <h2>Detection Breakdown</h2>
    <h3>By Severity</h3>
    {_render_severity_table(data['detections_by_severity'])}
    <h3>By Detector</h3>
    {_render_detector_table(data['detections_by_detector'])}

    <h2>Incident Timeline</h2>
    {_render_incident_table(data['incidents'])}

    <h2>Policy Configuration</h2>
    {_render_policies(data['policies'])}

    <h2>Agent Inventory</h2>
    {_render_agent_table(data['agents'])}

    <p class="footer-note">
      Generated by Parry. This report is intended for compliance review
      purposes (SOC 2, EU AI Act, ISO 27001). Raw prompt and response
      content is intentionally omitted to satisfy GDPR data
      minimization requirements.
    </p>
    """

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Parry Compliance Report — {escape(org['name'])}</title>
<style>{_STYLE}</style></head>
<body>{cover}{body}</body></html>"""


def render_report_pdf(data: dict[str, Any]) -> bytes:
    """Render report data to PDF bytes via WeasyPrint.

    Imported lazily so the rest of the app (and unit tests that don't
    need PDF output) don't pay for WeasyPrint's native dependencies at
    import time.
    """
    from weasyprint import HTML  # type: ignore[import-not-found]

    html = render_report_html(data)
    return HTML(string=html).write_pdf()
