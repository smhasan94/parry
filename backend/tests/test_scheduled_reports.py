"""Tests for scheduled reports — next_send computation, model, schemas."""

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import ScheduledReport
from app.services.scheduled_report_service import compute_next_send


class TestComputeNextSend:
    def test_weekly_future(self) -> None:
        # A Wednesday → next Monday
        wed = datetime(2026, 4, 8, 10, 0, 0, tzinfo=UTC)  # Wednesday
        result = compute_next_send("weekly", wed)
        assert result.weekday() == 0  # Monday
        assert result.hour == 8
        assert result > wed

    def test_weekly_monday_before_8(self) -> None:
        mon_early = datetime(2026, 4, 6, 6, 0, 0, tzinfo=UTC)  # Monday 6am
        result = compute_next_send("weekly", mon_early)
        assert result.day == 6  # Same Monday
        assert result.hour == 8

    def test_weekly_monday_after_8(self) -> None:
        mon_late = datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC)  # Monday 10am
        result = compute_next_send("weekly", mon_late)
        assert result.day == 13  # Next Monday
        assert result.hour == 8

    def test_monthly_mid_month(self) -> None:
        mid = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
        result = compute_next_send("monthly", mid)
        assert result.month == 5
        assert result.day == 1
        assert result.hour == 8

    def test_monthly_december(self) -> None:
        dec = datetime(2026, 12, 15, 10, 0, 0, tzinfo=UTC)
        result = compute_next_send("monthly", dec)
        assert result.year == 2027
        assert result.month == 1
        assert result.day == 1

    def test_monthly_first_of_month(self) -> None:
        first = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
        result = compute_next_send("monthly", first)
        assert result.month == 5

    def test_result_has_utc(self) -> None:
        result = compute_next_send("weekly")
        assert result.tzinfo is not None


class TestScheduledReportModel:
    def test_construction(self) -> None:
        r = ScheduledReport(
            org_id=uuid.uuid4(),
            schedule="weekly",
            recipients=["alice@acme.com", "bob@acme.com"],
            next_send_at=datetime.now(UTC) + timedelta(days=7),
        )
        assert r.schedule == "weekly"
        assert len(r.recipients) == 2
        assert r.last_sent_at is None

    def test_monthly_schedule(self) -> None:
        r = ScheduledReport(
            org_id=uuid.uuid4(),
            schedule="monthly",
            recipients=["team@acme.com"],
            report_type="compliance_posture",
            next_send_at=datetime.now(UTC) + timedelta(days=30),
        )
        assert r.schedule == "monthly"
        assert r.report_type == "compliance_posture"


class TestScheduledReportSchemas:
    def test_create_request(self) -> None:
        from app.api.v1.scheduled_reports import ScheduleCreateRequest

        req = ScheduleCreateRequest(
            schedule="weekly",
            recipients=["alice@acme.com"],
        )
        assert req.schedule == "weekly"
        assert req.report_type == "security_summary"

    def test_update_request(self) -> None:
        from app.api.v1.scheduled_reports import ScheduleUpdateRequest

        req = ScheduleUpdateRequest(is_active=False)
        assert req.is_active is False
        assert req.schedule is None

    def test_response(self) -> None:
        from app.api.v1.scheduled_reports import ScheduleResponse

        resp = ScheduleResponse(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            schedule="monthly",
            recipients=["team@acme.com"],
            report_type="security_summary",
            is_active=True,
            last_sent_at=None,
            next_send_at="2026-05-01T08:00:00Z",
            created_at="2026-04-10T00:00:00Z",
            updated_at="2026-04-10T00:00:00Z",
        )
        assert resp.is_active is True
