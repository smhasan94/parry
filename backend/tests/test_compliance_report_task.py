"""Unit tests for the async compliance-report Celery task.

The DB-bound body (build_report_data over real Postgres) is exercised
in tests/e2e/test_reports_async_flow.py; here we lock down the
status transitions and error handling around it, mocking the DB
session factory and the PDF renderer.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.compliance_report_task import _generate, generate_compliance_report


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


async def _raising_generate(*args: object, **kwargs: object) -> None:
    raise RuntimeError("simulated failure _generate's own except never saw")


def test_task_wrapper_sets_failed_status_as_a_safety_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer task wrapper must set "failed" independently of
    _generate's own except clause — some failures (e.g. a soft time
    limit interrupting the event loop between coroutine steps) never
    reach _generate's try/except at all, only the outer one.
    """
    monkeypatch.setattr(
        "app.workers.compliance_report_task._generate", _raising_generate
    )

    with patch("app.services.report_job_service.set_report_job_status") as set_status:
        with pytest.raises(RuntimeError):
            generate_compliance_report(
                "job-3",
                "11111111-1111-1111-1111-111111111111",
                "2026-01-01T00:00:00+00:00",
                "2026-04-01T00:00:00+00:00",
            )

    set_status.assert_any_call(
        "job-3", org_id="11111111-1111-1111-1111-111111111111", status="failed"
    )


def test_task_does_not_autoretry_permanent_failures() -> None:
    """A soft-time-limit hit, a missing org, or missing WeasyPrint
    native deps will fail again on retry — burning 3 attempts (~15
    minutes of worker CPU under this task's backoff config) buys
    nothing. These must be excluded from the blanket
    autoretry_for=(Exception,).
    """
    from celery.exceptions import SoftTimeLimitExceeded

    non_retryable = generate_compliance_report.dont_autoretry_for
    assert SoftTimeLimitExceeded in non_retryable
    assert ValueError in non_retryable
    assert ImportError in non_retryable
    assert OSError in non_retryable
