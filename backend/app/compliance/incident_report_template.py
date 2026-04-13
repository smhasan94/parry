"""Article 73 serious incident report HTML template + WeasyPrint renderer."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import SeriousIncident

_STYLE = """
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
       font-size: 11pt; line-height: 1.6; color: #1a1a1a; margin: 40px; }
h1 { font-size: 18pt; color: #991b1b; border-bottom: 2px solid #dc2626;
     padding-bottom: 8px; }
h2 { font-size: 13pt; color: #1e40af; margin-top: 24px;
     border-bottom: 1px solid #dbeafe; padding-bottom: 4px; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
th, td { text-align: left; padding: 6px 10px; border: 1px solid #e5e7eb;
         font-size: 10pt; }
th { background: #f3f4f6; font-weight: 600; width: 200px; }
.deadline { padding: 8px 12px; background: #fef2f2; border: 1px solid #fecaca;
            border-radius: 4px; font-weight: 600; color: #991b1b; margin: 12px 0; }
.disclaimer { margin-top: 32px; padding: 12px; background: #f9fafb;
              border: 1px solid #e5e7eb; font-size: 9pt; color: #6b7280; }
.empty { color: #9ca3af; font-style: italic; }
@page { size: A4; margin: 2cm; @bottom-center { content: "Page " counter(page)
        " of " counter(pages); font-size: 8pt; color: #9ca3af; } }
"""


def _val(v: object) -> str:
    if v is None:
        return '<span class="empty">Not provided</span>'
    return escape(str(v))


def render_incident_html(report: SeriousIncident) -> str:
    c = report.report_content or {}
    summary = c.get("incident_summary", {})
    contact = c.get("contact_information", {})
    authority = c.get("authority_information", {})

    deadline_str = (
        report.deadline_at.strftime("%Y-%m-%d %H:%M UTC") if report.deadline_at else "N/A"
    )
    reported_str = (
        " | <strong>REPORTED</strong> on "
        + report.reported_to_authority_at.strftime("%Y-%m-%d")
        if report.reported_to_authority_at
        else ""
    )
    jurisdiction = _val(report.authority_jurisdiction or authority.get("authority_jurisdiction"))

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Serious Incident Report — Art. 73</title>
<style>{_STYLE}</style></head><body>
<h1>Serious Incident Report</h1>
<p class="meta">EU AI Act — Article 73 | Report Version {report.report_version}</p>

<div class="deadline">Reporting deadline: {deadline_str}
{reported_str}</div>

<h2>Incident Summary</h2>
<table>
<tr><th>Title</th><td>{_val(summary.get('title'))}</td></tr>
<tr><th>Severity</th><td>{_val(summary.get('severity'))}</td></tr>
<tr><th>Detected at</th><td>{_val(summary.get('detected_at'))}</td></tr>
<tr><th>Resolved at</th><td>{_val(summary.get('resolved_at'))}</td></tr>
</table>

<h2>Description of Incident</h2>
<p>{_val(c.get('description_of_incident'))}</p>

<h2>Affected Persons</h2>
<p>{_val(c.get('affected_persons'))}</p>

<h2>Measures Taken</h2>
<p>{_val(c.get('measures_taken'))}</p>

<h2>Root Cause Analysis</h2>
<p>{_val(c.get('root_cause_analysis'))}</p>

<h2>Corrective Actions</h2>
<p>{_val(c.get('corrective_actions'))}</p>

<h2>Contact Information</h2>
<table>
<tr><th>Officer Name</th><td>{_val(contact.get('reporting_officer_name'))}</td></tr>
<tr><th>Title</th><td>{_val(contact.get('reporting_officer_title'))}</td></tr>
<tr><th>Email</th><td>{_val(contact.get('reporting_officer_email'))}</td></tr>
<tr><th>Phone</th><td>{_val(contact.get('reporting_officer_phone'))}</td></tr>
</table>

<h2>Authority Information</h2>
<table>
<tr><th>Authority</th><td>{_val(authority.get('authority_name'))}</td></tr>
<tr><th>Jurisdiction</th><td>{jurisdiction}</td></tr>
<tr><th>Reference #</th><td>{_val(authority.get('reference_number'))}</td></tr>
</table>

<div class="disclaimer">
<strong>Disclaimer:</strong> This report was generated using Parry's compliance
tools to assist with Article 73 serious incident reporting. The deployer is
responsible for ensuring accuracy and completeness before submission to the
relevant authority.
</div>
</body></html>"""
    return html


def render_incident_pdf(report: SeriousIncident) -> bytes:
    """Render serious incident report to PDF via WeasyPrint (lazy import)."""
    from weasyprint import HTML  # type: ignore[import-not-found]

    html = render_incident_html(report)
    return HTML(string=html).write_pdf()
