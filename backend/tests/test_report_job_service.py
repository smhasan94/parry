"""Unit tests for the compliance report async-job Redis helpers.

Mirrors the auditor-bundle job pattern (auditor_bundle_task.py) but
stores org_id alongside status so the download route can reject
cross-org access — see Review Focus in the plan this file implements.
"""
from __future__ import annotations

import fakeredis
import pytest

from app.services import report_job_service as job_svc


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(job_svc, "sync_redis", lambda: fake)
    monkeypatch.setattr(job_svc, "sync_redis_raw", lambda: fake)


def test_set_and_get_report_job_status_round_trips_org_id() -> None:
    job_svc.set_report_job_status("job-1", org_id="org-a", status="queued")

    result = job_svc.get_report_job_status("job-1")

    assert result == {"status": "queued", "org_id": "org-a"}


def test_get_report_job_status_returns_none_for_unknown_job() -> None:
    assert job_svc.get_report_job_status("nonexistent") is None


def test_store_and_load_report_pdf_round_trips_bytes() -> None:
    job_svc.store_report_pdf("job-2", b"%PDF-1.4 fake bytes")

    assert job_svc.load_report_pdf("job-2") == b"%PDF-1.4 fake bytes"


def test_load_report_pdf_returns_none_when_never_stored() -> None:
    assert job_svc.load_report_pdf("never-stored") is None


def test_set_report_job_status_overwrites_previous_status() -> None:
    job_svc.set_report_job_status("job-3", org_id="org-a", status="queued")
    job_svc.set_report_job_status("job-3", org_id="org-a", status="running")

    result = job_svc.get_report_job_status("job-3")

    assert result is not None
    assert result["status"] == "running"
