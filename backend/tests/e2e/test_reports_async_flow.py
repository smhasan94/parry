"""End-to-end: request a >90-day compliance report, run the task body
directly against the real test DB (no Celery worker in e2e), then
poll status and download — asserting the full round trip and that
another org cannot see or download the job.
"""
from __future__ import annotations

import fakeredis
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Org, Plan
from app.services import report_job_service as job_svc
from app.workers.compliance_report_task import _generate
from tests.e2e.conftest import TEST_DB_URL


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same convention as tests/test_report_job_service.py — this file
    should not depend on a real Redis being up on this machine.
    """
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(job_svc, "sync_redis", lambda: fake)
    monkeypatch.setattr(job_svc, "sync_redis_raw", lambda: fake)


@pytest.mark.asyncio
async def test_full_async_report_round_trip(
    admin_client: AsyncClient, seeded_db: dict, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    def fake_delay(job_id, org_id, start_iso, end_iso):
        captured["args"] = (job_id, org_id, start_iso, end_iso)

    monkeypatch.setattr(
        "app.workers.compliance_report_task.generate_compliance_report",
        type("T", (), {"delay": staticmethod(fake_delay)})(),
    )

    # _generate calls make_task_session_factory(), which by default binds
    # to settings.database_url (the app's real DB) — not this e2e suite's
    # TEST_DB_URL. Point it at the test DB, same fix as
    # tests/e2e/test_webhook_delivery_ssrf.py.
    task_engine = create_async_engine(TEST_DB_URL, echo=False)
    task_factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.make_task_session_factory", lambda: task_factory)

    resp = await admin_client.get(
        "/api/v1/reports/compliance",
        params={"start": "2026-01-01", "end": "2026-06-01"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert captured["args"][0] == job_id

    # Run the task body directly against the real e2e DB — no Celery
    # worker runs in this suite, matching how detection_task is
    # exercised synchronously elsewhere in tests/e2e/.
    job_id, org_id, start_iso, end_iso = captured["args"]
    try:
        result = await _generate(job_id, org_id, start_iso, end_iso)
    except (ImportError, OSError) as e:
        pytest.skip(f"WeasyPrint native dependencies unavailable: {e}")
    finally:
        await task_engine.dispose()
    assert result["status"] == "completed"

    status_resp = await admin_client.get(f"/api/v1/reports/compliance/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"
    assert status_resp.json()["download_url"] is not None

    download_resp = await admin_client.get(
        f"/api/v1/reports/compliance/jobs/{job_id}/download"
    )
    assert download_resp.status_code == 200
    assert download_resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_other_org_cannot_poll_or_download_job(
    admin_client: AsyncClient,
    seeded_db: dict,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.dependencies import Actor, get_current_actor, get_current_org
    from app.main import app
    from app.workers.compliance_report_task import _generate

    monkeypatch.setattr(
        "app.workers.compliance_report_task.generate_compliance_report",
        type("T", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
    )

    resp = await admin_client.get(
        "/api/v1/reports/compliance",
        params={"start": "2026-01-01", "end": "2026-06-01"},
    )
    job_id = resp.json()["job_id"]

    # Confirm the owning org actually sees the job before proving the
    # other org can't — otherwise a broken store (e.g. Redis down)
    # would make both orgs get 404 and this test would pass having
    # verified nothing about isolation.
    own_status_resp = await admin_client.get(f"/api/v1/reports/compliance/jobs/{job_id}")
    assert own_status_resp.status_code == 200

    other_org = Org(
        name="Other Org", clerk_org_id="clerk_other_org", is_active=True, plan=Plan.GROWTH
    )
    db.add(other_org)
    await db.flush()
    await db.commit()

    other_actor = Actor(
        actor_type="user", actor_id="other-admin", label="other@example.com", clerk_role="org:owner"
    )

    async def _override_actor():
        return (other_org, other_actor)

    async def _override_org():
        return other_org

    app.dependency_overrides[get_current_actor] = _override_actor
    app.dependency_overrides[get_current_org] = _override_org
    try:
        status_resp = await admin_client.get(f"/api/v1/reports/compliance/jobs/{job_id}")
        assert status_resp.status_code == 404

        download_resp = await admin_client.get(
            f"/api/v1/reports/compliance/jobs/{job_id}/download"
        )
        assert download_resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_current_org, None)
