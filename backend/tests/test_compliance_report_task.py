"""Unit tests for the async compliance-report Celery task.

The DB-bound body (build_report_data over real Postgres) is exercised
in tests/e2e/test_reports_async_flow.py; here we lock down the
status transitions and error handling around it, mocking the DB
session factory and the PDF renderer.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.compliance_report_task import _generate


@pytest.mark.asyncio
async def test_generate_sets_running_then_completed_on_success() -> None:
    fake_session = AsyncMock()
    fake_factory = MagicMock(return_value=fake_session)
    fake_factory.kw = {"bind": AsyncMock()}
    fake_session.__aenter__.return_value = fake_session
    fake_session.__aexit__.return_value = None

    with (
        patch("app.db.session.make_task_session_factory", return_value=fake_factory),
        patch(
            "app.services.report_service.build_report_data",
            new=AsyncMock(return_value={"summary": {"total_events": 1}}),
        ),
        patch(
            "app.services.report_template.render_report_pdf",
            return_value=b"%PDF-1.4 fake",
        ),
        patch("app.services.report_job_service.set_report_job_status") as set_status,
        patch("app.services.report_job_service.store_report_pdf") as store_pdf,
    ):
        result = await _generate(
            job_id="job-1",
            org_id="11111111-1111-1111-1111-111111111111",
            start_iso="2026-01-01T00:00:00+00:00",
            end_iso="2026-04-01T00:00:00+00:00",
        )

    assert result["status"] == "completed"
    set_status.assert_any_call("job-1", org_id="11111111-1111-1111-1111-111111111111", status="running")
    set_status.assert_any_call("job-1", org_id="11111111-1111-1111-1111-111111111111", status="completed")
    store_pdf.assert_called_once_with("job-1", b"%PDF-1.4 fake")


@pytest.mark.asyncio
async def test_generate_sets_failed_status_when_render_raises() -> None:
    fake_session = AsyncMock()
    fake_factory = MagicMock(return_value=fake_session)
    fake_factory.kw = {"bind": AsyncMock()}
    fake_session.__aenter__.return_value = fake_session
    fake_session.__aexit__.return_value = None

    with (
        patch("app.db.session.make_task_session_factory", return_value=fake_factory),
        patch(
            "app.services.report_service.build_report_data",
            new=AsyncMock(return_value={"summary": {}}),
        ),
        patch(
            "app.services.report_template.render_report_pdf",
            side_effect=ImportError("weasyprint missing"),
        ),
        patch("app.services.report_job_service.set_report_job_status") as set_status,
    ):
        with pytest.raises(ImportError):
            await _generate(
                job_id="job-2",
                org_id="11111111-1111-1111-1111-111111111111",
                start_iso="2026-01-01T00:00:00+00:00",
                end_iso="2026-04-01T00:00:00+00:00",
            )

    set_status.assert_any_call("job-2", org_id="11111111-1111-1111-1111-111111111111", status="failed")
