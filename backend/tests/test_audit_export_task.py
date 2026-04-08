"""Unit tests for the monthly audit export task helpers.

The Celery task body is DB + S3 bound and covered in e2e tests;
here we lock down _previous_month_range, which is pure and trivially
broken by off-by-one errors.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.workers.audit_export_task import _previous_month_range


def test_mid_year_previous_month() -> None:
    start, end, label = _previous_month_range(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    assert label == "2026-04"
    assert start == datetime(2026, 4, 1, tzinfo=UTC)
    assert end == datetime(2026, 5, 1, tzinfo=UTC)


def test_january_rolls_to_previous_year_december() -> None:
    start, end, label = _previous_month_range(datetime(2026, 1, 2, 0, 0, tzinfo=UTC))
    assert label == "2025-12"
    assert start == datetime(2025, 12, 1, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, tzinfo=UTC)


def test_december_previous_is_november() -> None:
    start, end, label = _previous_month_range(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert label == "2026-11"
    assert start == datetime(2026, 11, 1, tzinfo=UTC)
    assert end == datetime(2026, 12, 1, tzinfo=UTC)


def test_leap_year_february_previous_is_january() -> None:
    start, end, label = _previous_month_range(datetime(2028, 2, 10, 12, 0, tzinfo=UTC))
    assert label == "2028-01"
    assert start == datetime(2028, 1, 1, tzinfo=UTC)
    assert end == datetime(2028, 2, 1, tzinfo=UTC)


def test_range_is_half_open() -> None:
    # The end should be the first moment of the next month, never the
    # last microsecond of the reported month — matches the convention
    # used everywhere else in the codebase.
    _, end, _ = _previous_month_range(datetime(2026, 6, 1, 0, 0, tzinfo=UTC))
    assert end == datetime(2026, 6, 1, tzinfo=UTC)
    assert end.day == 1
