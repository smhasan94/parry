"""API tests for the async compliance-report dispatch/status/download
routes. Mirrors the dependency_overrides + monkeypatch style in
tests/e2e/conftest.py's `client`/`admin_client` fixtures — those
fixtures are session-scoped for the whole app, so we reuse them here
rather than re-deriving a lighter-weight client.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_range_over_90_days_dispatches_async_job(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_task = MagicMock()
    monkeypatch.setattr(
        "app.workers.compliance_report_task.generate_compliance_report", fake_task
    )

    resp = await admin_client.get(
        "/api/v1/reports/compliance",
        params={"start": "2026-01-01", "end": "2026-06-01"},  # 151 days > 90
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "job_id" in body
    fake_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_range_over_366_days_still_rejected(admin_client: AsyncClient) -> None:
    resp = await admin_client.get(
        "/api/v1/reports/compliance",
        params={"start": "2026-01-01", "end": "2027-06-01"},  # > 366 days
    )

    assert resp.status_code == 400
    assert "Maximum supported range" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_status_route_returns_404_for_unknown_job(admin_client: AsyncClient) -> None:
    resp = await admin_client.get("/api/v1/reports/compliance/jobs/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_route_returns_running_job(
    admin_client: AsyncClient, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report_job_service

    org_id = str(seeded_db["org"].id)
    monkeypatch.setattr(
        report_job_service,
        "get_report_job_status",
        lambda job_id: {"status": "running", "org_id": org_id} if job_id == "job-x" else None,
    )

    resp = await admin_client.get("/api/v1/reports/compliance/jobs/job-x")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_status_route_rejects_other_orgs_job(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report_job_service

    monkeypatch.setattr(
        report_job_service,
        "get_report_job_status",
        lambda job_id: {"status": "completed", "org_id": "some-other-org"},
    )

    resp = await admin_client.get("/api/v1/reports/compliance/jobs/job-y")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_route_returns_pdf_bytes(
    admin_client: AsyncClient, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report_job_service

    org_id = str(seeded_db["org"].id)
    monkeypatch.setattr(
        report_job_service,
        "get_report_job_status",
        lambda job_id: {"status": "completed", "org_id": org_id},
    )
    monkeypatch.setattr(
        report_job_service, "load_report_pdf", lambda job_id: b"%PDF-1.4 fake"
    )

    resp = await admin_client.get("/api/v1/reports/compliance/jobs/job-z/download")

    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 fake"
    assert resp.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_download_route_returns_404_when_pdf_expired_but_status_completed(
    admin_client: AsyncClient, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report_job_service

    org_id = str(seeded_db["org"].id)
    monkeypatch.setattr(
        report_job_service,
        "get_report_job_status",
        lambda job_id: {"status": "completed", "org_id": org_id},
    )
    monkeypatch.setattr(report_job_service, "load_report_pdf", lambda job_id: None)

    resp = await admin_client.get("/api/v1/reports/compliance/jobs/job-w/download")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_route_returns_409_when_job_not_yet_completed(
    admin_client: AsyncClient, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report_job_service

    org_id = str(seeded_db["org"].id)
    monkeypatch.setattr(
        report_job_service,
        "get_report_job_status",
        lambda job_id: {"status": "running", "org_id": org_id},
    )

    resp = await admin_client.get("/api/v1/reports/compliance/jobs/job-v/download")

    assert resp.status_code == 409
