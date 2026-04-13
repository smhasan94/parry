"""Celery task: check and send due scheduled reports.

Runs hourly. For each due report, generates PDF via report_service
and sends via SMTP to all recipients.
"""

import asyncio
from datetime import UTC, datetime

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="send_due_reports",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def send_due_reports(self) -> dict:  # type: ignore[no-untyped-def]
    """Check for due scheduled reports and send them."""
    try:
        return asyncio.run(_send_all())
    except Exception:
        log.error(
            "scheduled_reports.task_failed",
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _send_all() -> dict:
    from app.db.models import Org
    from app.db.session import make_task_session_factory
    from app.services.scheduled_report_service import compute_next_send, get_due_schedules

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    sent = 0
    errors = 0

    try:
        async with factory() as db:
            due = await get_due_schedules(db)
            log.info("scheduled_reports.checking", due_count=len(due))

            for schedule in due:
                try:
                    org = await db.get(Org, schedule.org_id)
                    if org is None:
                        continue

                    await _generate_and_send(db, schedule, org)

                    # Update timestamps
                    schedule.last_sent_at = datetime.now(UTC)
                    schedule.next_send_at = compute_next_send(schedule.schedule)
                    sent += 1

                except Exception:
                    log.warning(
                        "scheduled_reports.send_failed",
                        report_id=str(schedule.id),
                        exc_info=True,
                    )
                    errors += 1

            await db.commit()

        log.info(
            "scheduled_reports.completed",
            sent=sent,
            errors=errors,
        )
        return {"sent": sent, "errors": errors}
    finally:
        await task_engine.dispose()


async def _generate_and_send(db, schedule, org) -> None:
    """Generate report PDF and send via email."""
    from datetime import timedelta

    from app.services.report_service import build_report_data

    # Build report data for the last period
    days = 7 if schedule.schedule == "weekly" else 30

    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    report_data = await build_report_data(
        db, org.id, start=start, end=end
    )

    # Add metadata
    report_data["schedule_type"] = schedule.schedule
    report_data["report_type"] = schedule.report_type

    # Render PDF
    try:
        from app.services.report_template import render_report_pdf

        pdf_bytes = render_report_pdf(report_data)
    except ImportError:
        log.warning("scheduled_reports.weasyprint_missing")
        pdf_bytes = None
    except Exception:
        log.warning("scheduled_reports.pdf_failed", exc_info=True)
        pdf_bytes = None

    # Send email to all recipients
    recipients = schedule.recipients or []
    if not recipients:
        log.info("scheduled_reports.no_recipients", report_id=str(schedule.id))
        return

    subject = (
        f"Parry {schedule.schedule.title()} Security Report — {org.name}"
    )

    html_body = f"""
    <h2>Parry {schedule.schedule.title()} Security Report</h2>
    <p>Organization: <strong>{org.name}</strong></p>
    <p>Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}</p>
    <p>Report type: {schedule.report_type.replace('_', ' ').title()}</p>
    <hr>
    <p>Summary:</p>
    <ul>
        <li>Total events: {report_data.get('total_events', 'N/A')}</li>
        <li>Detections triggered: {report_data.get('detections_triggered', 'N/A')}</li>
        <li>Incidents created: {report_data.get('incidents_created', 'N/A')}</li>
    </ul>
    <p><em>Full PDF report attached (if available).</em></p>
    <hr>
    <p style="font-size:11px;color:#888;">
        This is an automated report from Parry. Manage your report
        schedule in the Parry dashboard under Reports.
    </p>
    """

    try:
        import asyncio

        from app.services.alert_service import _send_email_sync

        # For scheduled reports with PDF, we need a custom send
        # that attaches the PDF. Fall back to plain HTML if no PDF.
        if pdf_bytes:
            _send_report_email(recipients, subject, html_body, pdf_bytes)
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _send_email_sync, recipients, subject, html_body
            )
    except Exception:
        log.warning("scheduled_reports.email_failed", exc_info=True)
        raise


def _send_report_email(
    to_addresses: list[str],
    subject: str,
    html_body: str,
    pdf_bytes: bytes,
) -> None:
    """Send email with PDF attachment via SMTP."""
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from app.core.config import settings

    if not settings.smtp_host:
        log.warning("scheduled_reports.smtp_not_configured")
        return

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to_addresses)

    # HTML body
    msg.attach(MIMEText(html_body, "html"))

    # PDF attachment
    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header(
        "Content-Disposition", "attachment", filename="parry-report.pdf"
    )
    msg.attach(pdf_part)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, to_addresses, msg.as_string())
