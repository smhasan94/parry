"""FRIA HTML template + WeasyPrint renderer.

Inline CSS so WeasyPrint renders fully offline. Lazy import of
weasyprint so the rest of the app doesn't need native deps at import.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import FRIADocument

_STYLE = """
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
       font-size: 11pt; line-height: 1.6; color: #1a1a1a; margin: 40px; }
h1 { font-size: 20pt; color: #111827; border-bottom: 2px solid #2563eb;
     padding-bottom: 8px; margin-top: 0; }
h2 { font-size: 14pt; color: #1e40af; margin-top: 28px;
     border-bottom: 1px solid #dbeafe; padding-bottom: 4px; }
h3 { font-size: 12pt; color: #374151; margin-top: 16px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 8px 12px; border: 1px solid #e5e7eb;
         font-size: 10pt; }
th { background: #f3f4f6; font-weight: 600; }
.meta { color: #6b7280; font-size: 9pt; margin-bottom: 4px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
         font-size: 9pt; font-weight: 600; }
.badge-high { background: #fef2f2; color: #991b1b; }
.badge-limited { background: #fffbeb; color: #92400e; }
.badge-minimal { background: #f0fdf4; color: #166534; }
.disclaimer { margin-top: 32px; padding: 12px; background: #f9fafb;
              border: 1px solid #e5e7eb; font-size: 9pt; color: #6b7280; }
.empty { color: #9ca3af; font-style: italic; }
.field-label { font-weight: 600; color: #374151; min-width: 180px; }
@page { size: A4; margin: 2cm; @bottom-center { content: "Page " counter(page)
        " of " counter(pages); font-size: 8pt; color: #9ca3af; } }
"""


def _risk_badge(level: str) -> str:
    cls = {"high": "badge-high", "limited": "badge-limited"}.get(
        level, "badge-minimal"
    )
    return f'<span class="badge {cls}">{escape(level.upper())}</span>'


def _render_field_value(value: object) -> str:
    if value is None:
        return '<span class="empty">Not provided</span>'
    if isinstance(value, list):
        if not value:
            return '<span class="empty">None</span>'
        items = "".join(f"<li>{escape(str(v))}</li>" for v in value)
        return f"<ul>{items}</ul>"
    if isinstance(value, dict):
        rows = "".join(
            f"<tr><td class='field-label'>{escape(str(k))}</td>"
            f"<td>{_render_field_value(v)}</td></tr>"
            for k, v in value.items()
        )
        return f"<table>{rows}</table>"
    return escape(str(value))


def render_fria_html(doc: FRIADocument) -> str:
    """Render a FRIADocument to an HTML string."""
    content = doc.content or {}
    sections_data = content.get("sections", {})

    # Cover
    system_section = sections_data.get("system_identification", {})
    system_fields = system_section.get("fields", {})
    system_name = system_fields.get("system_name", "Unknown System")
    risk_level = system_fields.get("risk_level", "unknown")

    cover = f"""
    <h1>Fundamental Rights Impact Assessment (FRIA)</h1>
    <table>
      <tr><td class="field-label">System</td>
          <td>{escape(str(system_name))}</td></tr>
      <tr><td class="field-label">Risk Classification</td>
          <td>{_risk_badge(str(risk_level))}</td></tr>
      <tr><td class="field-label">Version</td>
          <td>{doc.version}</td></tr>
      <tr><td class="field-label">Generated</td>
          <td>{doc.generated_at.strftime('%Y-%m-%d %H:%M UTC') if doc.generated_at else 'N/A'}</td></tr>
      <tr><td class="field-label">Status</td>
          <td>{escape(doc.status.upper())}</td></tr>
    """
    if doc.approved_by:
        cover += f"""
      <tr><td class="field-label">Approved by</td>
          <td>{escape(doc.approved_by)}
              {(' — ' + escape(doc.approver_title)) if doc.approver_title else ''}</td></tr>
      <tr><td class="field-label">Approved on</td>
          <td>{doc.approved_at.strftime('%Y-%m-%d') if doc.approved_at else 'N/A'}</td></tr>
      <tr><td class="field-label">Next review</td>
          <td>{str(doc.next_review_date) if doc.next_review_date else 'N/A'}</td></tr>
    """
    cover += "</table>"

    # Sections
    body = ""
    for section_id, section_data in sections_data.items():
        title = section_data.get("title", section_id)
        fields = section_data.get("fields", {})

        body += f"<h2>{escape(title)}</h2>"

        if isinstance(fields, dict):
            body += "<table>"
            for key, value in fields.items():
                label = key.replace("_", " ").title()
                body += (
                    f"<tr><td class='field-label'>{escape(label)}</td>"
                    f"<td>{_render_field_value(value)}</td></tr>"
                )
            body += "</table>"
        elif isinstance(fields, list):
            body += "<table>"
            for item in fields:
                if isinstance(item, dict):
                    for k, v in item.items():
                        body += (
                            f"<tr><td class='field-label'>{escape(str(k))}</td>"
                            f"<td>{_render_field_value(v)}</td></tr>"
                        )
            body += "</table>"

    # Disclaimer
    disclaimer = """
    <div class="disclaimer">
    <strong>Disclaimer:</strong> This Fundamental Rights Impact Assessment was
    generated using Parry's compliance tools. It is not legal advice. The deployer
    remains solely responsible for compliance with the EU AI Act (Regulation
    2024/1689). Consult qualified legal counsel for definitive compliance guidance.
    </div>
    """

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>FRIA — {escape(str(system_name))}</title>
<style>{_STYLE}</style></head>
<body>{cover}{body}{disclaimer}</body></html>"""


def render_fria_pdf(doc: FRIADocument) -> bytes:
    """Render FRIA to PDF via WeasyPrint (lazy import)."""
    from weasyprint import HTML  # type: ignore[import-not-found]

    html = render_fria_html(doc)
    return HTML(string=html).write_pdf()
