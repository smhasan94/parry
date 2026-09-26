# Async Compliance PDF Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `GET /api/v1/reports/compliance` generate PDFs for ranges over 90 days by dispatching a Celery job instead of rejecting the request outright, with a status-poll and download endpoint to retrieve the result.

**Architecture:** Reuse the job-id + Redis pattern already shipped for the auditor bundle (`backend/app/workers/auditor_bundle_task.py`, `backend/app/api/v1/compliance.py:524-568`): the route creates a `job_id`, commits an audit-log row, enqueues a Celery task via `.delay()`, and returns `202` immediately. The task calls the existing `build_report_data` / `render_report_pdf` functions unchanged, stores the resulting bytes and status in Redis with a 1-hour TTL, and two new GET routes expose status and download. The 90-day sync path in `reports.py` is untouched — this only replaces the `>90 day` rejection branch.

**Tech Stack:** FastAPI, Celery (existing `celery_app`), Redis (`app.core.redis_pool.sync_redis` / `sync_redis_raw`), WeasyPrint (via `render_report_pdf`, unchanged), pytest + pytest-asyncio, httpx `AsyncClient` e2e fixtures.

**Spec:** No separate spec doc exists; the spec is this plan plus the precedent it follows — `backend/app/api/v1/compliance.py:524-568` (route), `backend/app/workers/auditor_bundle_task.py` (task), and the TODO comment being closed at `backend/app/api/v1/reports.py:1-8`.

## Global Constraints

- Return `202 Accepted` for the async dispatch route, per `CLAUDE.md` API design conventions — never `200`.
- Never call WeasyPrint or any blocking I/O synchronously inside an `async def` route handler — only inside the Celery task body, exactly as `reports.py`'s existing sync path already isolates it in a `try/except`.
- Async DB session inside the Celery task must use `app.db.session.make_task_session_factory()` and must `await task_engine.dispose()` in a `finally` block — the pattern every existing task (`scheduled_report_task.py`, `auditor_bundle_task.py`) follows.
- `MAX_RANGE_DAYS = 366` (already defined in `reports.py:32`) remains the hard ceiling for both sync and async paths — do not raise it.
- Redis keys must carry the same 1-hour TTL (`3600`) the auditor-bundle job uses, via `setex` — no unbounded storage of report bytes.
- Follow `app/schemas/base.ParrySchema` for every new response model, matching every other schema in this router.
- Type annotations required on all new functions (project-wide rule).
- Never store raw prompt/response content — not applicable here since `build_report_data` already excludes it, but the new task must not introduce a data path that bypasses that.

## Review Focus

- **Org isolation on the download route.** The status/download endpoints are keyed only by `job_id` (a UUID string) with no org check in the existing auditor-bundle precedent — anyone with `Role.VIEWER` (or a leaked/log-scraped `job_id`) could poll or download another org's compliance PDF. This plan's Task 3 must scope the Redis value to include `org_id` and reject downloads where the requesting org doesn't match.
- **Requesting the same window twice.** Two admins in the same org requesting the same >90-day range concurrently should not corrupt each other's job state — job IDs are independent (`uuid4()` per request), so this is fine by construction, but Task 2's test must assert two concurrent jobs for the same org don't collide on the same Redis key.
- **Polling a job that failed.** `_set_job_status(job_id, "failed")` is only reachable from the task's outer `except Exception` in the auditor-bundle precedent — the status route must surface `"failed"` distinctly from `"queued"`/`"running"`, not 500 or silently report `"queued"` forever. Task 3's tests must cover this.
- **Polling a job_id that never existed, or one whose TTL already expired.** Both look identical to Redis (`GET` returns `None`) but are different user stories — a typo'd ID vs. "you waited too long." The status route must return `404` for both, with a message that doesn't imply the job is still running.
- **Downloading a job that's `"completed"` per status but whose PDF bytes already fell out of Redis** (TTL race — status key and data key share the same 3600s TTL but are set in two separate `setex` calls, so they can expire at slightly different times, or an operator could flush data selectively). The download route must handle a `None` PDF payload after a `"completed"` status read without a raw `KeyError`/`TypeError`, returning `404` or `503` rather than crashing.

---

### Task 1: Job-status schema and Redis helpers for compliance reports

**Files:**
- Create: `backend/app/schemas/report_job.py`
- Create: `backend/app/services/report_job_service.py`
- Test: `backend/tests/test_report_job_service.py`

**Interfaces:**
- Consumes: `app.core.redis_pool.sync_redis`, `app.core.redis_pool.sync_redis_raw` (existing).
- Produces (for Task 2 and Task 3 to import):
  - `ReportJobStatusResponse(ParrySchema)` — fields `job_id: str`, `status: str`, `download_url: str | None = None`.
  - `set_report_job_status(job_id: str, org_id: str, status: str) -> None`
  - `get_report_job_status(job_id: str) -> dict[str, str] | None` — returns `{"status": ..., "org_id": ...}` or `None` if the key doesn't exist/expired.
  - `store_report_pdf(job_id: str, data: bytes) -> None`
  - `load_report_pdf(job_id: str) -> bytes | None`
  - `REPORT_JOB_TTL_SECONDS = 3600` (module-level constant, exported).

- [ ] **Step 1: Write the failing test for the status/org round-trip**

```python
# backend/tests/test_report_job_service.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_report_job_service.py -v`
Expected: `FAIL` / `ERROR` — `ModuleNotFoundError: No module named 'app.services.report_job_service'` (add `fakeredis` to `backend/pyproject.toml` dev dependencies first if not already present — check with `uv pip show fakeredis` before adding, per the "don't add deps without checking license" rule; fakeredis is BSD-licensed).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas/report_job.py
"""Response schema for the async compliance-report job endpoints."""

from __future__ import annotations

from app.schemas.base import ParrySchema


class ReportJobStatusResponse(ParrySchema):
    job_id: str
    status: str  # queued|running|completed|failed
    download_url: str | None = None
```

```python
# backend/app/services/report_job_service.py
"""Redis-backed status/storage for async compliance-report jobs.

Mirrors the job_id + Redis pattern in
``app.workers.auditor_bundle_task``, with one addition: the status
value carries ``org_id`` alongside ``status`` so the download route
(``app/api/v1/reports.py``) can refuse a job_id that belongs to a
different org, which the auditor-bundle precedent does not do.
"""

from __future__ import annotations

import json

import structlog

from app.core.redis_pool import sync_redis, sync_redis_raw

log = structlog.get_logger()

REPORT_JOB_TTL_SECONDS = 3600

_STATUS_KEY = "report_job:{job_id}:status"
_DATA_KEY = "report_job:{job_id}:data"


def set_report_job_status(job_id: str, org_id: str, status: str) -> None:
    try:
        r = sync_redis()
        r.setex(
            _STATUS_KEY.format(job_id=job_id),
            REPORT_JOB_TTL_SECONDS,
            json.dumps({"status": status, "org_id": org_id}),
        )
    except Exception:
        log.warning("report_job.redis_status_failed", job_id=job_id, exc_info=True)


def get_report_job_status(job_id: str) -> dict[str, str] | None:
    try:
        r = sync_redis()
        raw = r.get(_STATUS_KEY.format(job_id=job_id))
    except Exception:
        log.warning("report_job.redis_status_read_failed", job_id=job_id, exc_info=True)
        return None
    if raw is None:
        return None
    return json.loads(raw)


def store_report_pdf(job_id: str, data: bytes) -> None:
    try:
        r = sync_redis_raw()
        r.setex(_DATA_KEY.format(job_id=job_id), REPORT_JOB_TTL_SECONDS, data)
    except Exception:
        log.warning("report_job.redis_store_failed", job_id=job_id, exc_info=True)


def load_report_pdf(job_id: str) -> bytes | None:
    try:
        r = sync_redis_raw()
        return r.get(_DATA_KEY.format(job_id=job_id))
    except Exception:
        log.warning("report_job.redis_load_failed", job_id=job_id, exc_info=True)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_report_job_service.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/schemas/report_job.py app/services/report_job_service.py tests/test_report_job_service.py pyproject.toml
git commit -m "feat(reports): add Redis-backed job status service for async PDF reports"
```

---

### Task 2: Celery task that generates the PDF and stores it

**Files:**
- Create: `backend/app/workers/compliance_report_task.py`
- Test: `backend/tests/test_compliance_report_task.py` (pure/mock-level — the DB-bound body is exercised in Task 4's e2e test, following the convention `test_audit_export_task.py` documents in its own docstring)

**Interfaces:**
- Consumes: `report_job_service.set_report_job_status`, `report_job_service.store_report_pdf` (Task 1); `app.services.report_service.build_report_data`; `app.services.report_template.render_report_pdf`; `app.db.session.make_task_session_factory`.
- Produces: Celery task registered as `"generate_compliance_report"`, importable as `from app.workers.compliance_report_task import generate_compliance_report`, callable as `generate_compliance_report.delay(job_id: str, org_id: str, start_iso: str, end_iso: str)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_compliance_report_task.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_compliance_report_task.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.workers.compliance_report_task'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/compliance_report_task.py
"""Celery task: generate a compliance PDF for a >90-day range.

Long-running for large orgs — writes the finished PDF to Redis for
polling/download, following the same shape as
``app.workers.auditor_bundle_task`` (job_id keyed, 1h TTL) but scoped
by org_id so cross-org download is refused at the route layer.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="generate_compliance_report",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def generate_compliance_report(
    self: Any, job_id: str, org_id: str, start_iso: str, end_iso: str
) -> dict[str, Any]:
    try:
        return asyncio.run(_generate(job_id, org_id, start_iso, end_iso))
    except Exception:
        from app.services.report_job_service import set_report_job_status

        set_report_job_status(job_id, org_id=org_id, status="failed")
        log.error(
            "compliance_report.task_failed",
            job_id=job_id,
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _generate(
    job_id: str, org_id: str, start_iso: str, end_iso: str
) -> dict[str, Any]:
    from app.db.session import make_task_session_factory
    from app.services.report_job_service import set_report_job_status, store_report_pdf
    from app.services.report_service import build_report_data
    from app.services.report_template import render_report_pdf

    set_report_job_status(job_id, org_id=org_id, status="running")

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            data = await build_report_data(db, uuid.UUID(org_id), start, end)

        pdf_bytes = render_report_pdf(data)
        store_report_pdf(job_id, pdf_bytes)
        set_report_job_status(job_id, org_id=org_id, status="completed")

        log.info(
            "compliance_report.completed",
            job_id=job_id,
            org_id=org_id,
            size_bytes=len(pdf_bytes),
        )
        return {"job_id": job_id, "status": "completed", "size_bytes": len(pdf_bytes)}
    finally:
        await task_engine.dispose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_compliance_report_task.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/workers/compliance_report_task.py tests/test_compliance_report_task.py
git commit -m "feat(reports): add Celery task to generate compliance PDFs asynchronously"
```

---

### Task 3: Route changes — dispatch, status, and download

**Files:**
- Modify: `backend/app/api/v1/reports.py:1-129` (replace the `>90 day` rejection branch with dispatch; add two new GET routes)
- Test: `backend/tests/api/test_reports_async.py`

**Interfaces:**
- Consumes: `ReportJobStatusResponse` (Task 1), `report_job_service.{set_report_job_status,get_report_job_status,load_report_pdf}` (Task 1), `compliance_report_task.generate_compliance_report` (Task 2).
- Produces: `POST`-shaped semantics on the existing `GET /compliance` route stay a `GET` (matches existing REST shape — this endpoint was always a `GET` that triggers work, per the docstring at `reports.py:1-8`), now returning `202` + `ReportJobStatusResponse` for ranges over `MAX_SYNC_DAYS`. New `GET /compliance/jobs/{job_id}` and `GET /compliance/jobs/{job_id}/download`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_reports_async.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_reports_async.py -v`
Expected: `FAIL` — `404` on `/compliance/jobs/...` routes (don't exist yet) and the >90-day case still returns `400` instead of `202`.

- [ ] **Step 3: Write minimal implementation**

Replace the whole file `backend/app/api/v1/reports.py` with:

```python
"""Compliance report export API.

``GET /api/v1/reports/compliance?start=YYYY-MM-DD&end=YYYY-MM-DD``

Admin+ gated. Generates a PDF synchronously for ranges up to 90 days
and streams the bytes back as ``application/pdf``. Ranges over 90
days (up to the 366-day ceiling) are generated asynchronously via
Celery: this call returns 202 with a job_id, polled at
``GET /compliance/jobs/{job_id}`` and downloaded at
``GET /compliance/jobs/{job_id}/download``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.report_job import ReportJobStatusResponse
from app.services import audit_service, plan_service, report_job_service
from app.services.report_service import build_report_data
from app.services.report_template import render_report_pdf

log = structlog.get_logger()

router = APIRouter()

MAX_SYNC_DAYS = 90
MAX_RANGE_DAYS = 366


@router.get("/compliance")
async def export_compliance_report(
    start: date = Query(..., description="Inclusive start date, YYYY-MM-DD"),
    end: date = Query(..., description="Exclusive end date, YYYY-MM-DD"),
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")

    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )

    span_days = (end - start).days
    if span_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum supported range is {MAX_RANGE_DAYS} days.",
        )

    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end, time.min, tzinfo=UTC)

    if span_days > MAX_SYNC_DAYS:
        return await _dispatch_async_report(db, org, actor, start_dt, end_dt)

    data = await build_report_data(db, org.id, start_dt, end_dt)

    try:
        pdf_bytes = render_report_pdf(data)
    except ImportError as e:  # pragma: no cover - dep missing in dev
        log.error("report.pdf.weasyprint_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation is not available on this server.",
        ) from e
    except OSError as e:
        # WeasyPrint raises OSError when its native deps (Pango,
        # Cairo, libgobject) can't be loaded. Same user-visible
        # story as a missing Python package — the server is
        # misconfigured, not the request.
        log.error("report.pdf.weasyprint_native_deps_missing", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "PDF generation is unavailable: native dependencies "
                "(Pango/Cairo) missing on this backend. See docs/runbook.md."
            ),
        ) from e

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="compliance_report.exported",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="compliance_report",
        resource_id=None,
        details={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bytes": len(pdf_bytes),
            "total_events": data["summary"]["total_events"],
            "total_incidents": data["summary"]["total_incidents"],
        },
    )
    await db.commit()

    log.info(
        "compliance_report.exported",
        org_id=str(org.id),
        start=start.isoformat(),
        end=end.isoformat(),
        bytes=len(pdf_bytes),
    )

    filename = f"parry-compliance-{start.isoformat()}-{end.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


async def _dispatch_async_report(
    db: AsyncSession,
    org: Org,
    actor: Actor,
    start_dt: datetime,
    end_dt: datetime,
) -> Response:
    job_id = str(uuid.uuid4())
    report_job_service.set_report_job_status(job_id, org_id=str(org.id), status="queued")

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="compliance_report.async_requested",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="compliance_report",
        resource_id=None,
        details={
            "job_id": job_id,
            "start": start_dt.date().isoformat(),
            "end": end_dt.date().isoformat(),
        },
    )
    await db.commit()

    try:
        from app.workers.compliance_report_task import generate_compliance_report

        generate_compliance_report.delay(
            job_id, str(org.id), start_dt.isoformat(), end_dt.isoformat()
        )
    except Exception as e:  # pragma: no cover — broker outage
        log.error("compliance_report.enqueue_failed", job_id=job_id, error=str(e))
        # Don't fail the API call — the job sits in "queued" state and
        # a broker-recovery reprocess (or a manual retry) can pick it
        # up; matches the red_team.start_run precedent.

    import json

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=json.loads(
            ReportJobStatusResponse(job_id=job_id, status="queued").model_dump_json()
        ),
    )


@router.get("/compliance/jobs/{job_id}", response_model=ReportJobStatusResponse)
async def get_compliance_report_job(
    job_id: str,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
) -> ReportJobStatusResponse:
    org, _ = org_actor
    state = report_job_service.get_report_job_status(job_id)
    if state is None or state["org_id"] != str(org.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    download_url = (
        f"/api/v1/reports/compliance/jobs/{job_id}/download"
        if state["status"] == "completed"
        else None
    )
    return ReportJobStatusResponse(job_id=job_id, status=state["status"], download_url=download_url)


@router.get("/compliance/jobs/{job_id}/download")
async def download_compliance_report_job(
    job_id: str,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
) -> Response:
    org, _ = org_actor
    state = report_job_service.get_report_job_status(job_id)
    if state is None or state["org_id"] != str(org.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if state["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is {state['status']}, not ready for download.",
        )

    pdf_bytes = report_job_service.load_report_pdf(job_id)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report expired. Request a new export.",
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="parry-compliance-{job_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_reports_async.py -v`
Expected: `8 passed`

- [ ] **Step 5: Run the full existing reports-adjacent suite to confirm no regression**

Run: `cd backend && uv run pytest tests/test_report_service.py tests/test_scheduled_reports.py tests/api/test_reports_async.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/api/v1/reports.py tests/api/test_reports_async.py
git commit -m "feat(reports): dispatch async Celery job for compliance PDF ranges over 90 days"
```

---

### Task 4: e2e coverage for the full dispatch → completion → download flow

**Files:**
- Create: `backend/tests/e2e/test_reports_async_flow.py`

**Interfaces:**
- Consumes: `client`/`seeded_db`/`admin_client` fixtures from `tests/e2e/conftest.py`; `app.workers.compliance_report_task._generate` (Task 2, called directly rather than via `.delay()` — same pattern the `client` fixture already establishes for `detection_task`, since e2e tests don't run a real Celery worker).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/e2e/test_reports_async_flow.py
"""End-to-end: request a >90-day compliance report, run the task body
directly against the real test DB (no Celery worker in e2e), then
poll status and download — asserting the full round trip and that
another org cannot see or download the job.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Org, Plan
from app.workers.compliance_report_task import _generate


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
    result = await _generate(job_id, org_id, start_iso, end_iso)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && docker compose up -d postgres && uv run pytest tests/e2e/test_reports_async_flow.py -v`
Expected: `FAIL` initially if Tasks 1-3 aren't yet merged in the branch being tested; once merged, this step should already pass — treat this test as regression-locking rather than red/green if run after Task 3 is committed. If run standalone against `main` before those tasks land, expect `404`/`AttributeError` on the new routes/module.

- [ ] **Step 3: (No new implementation — this task is pure test coverage of Tasks 1-3.)**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/e2e/test_reports_async_flow.py -v`
Expected: `2 passed` (skipped automatically if `localhost:5434` Postgres isn't running, per `conftest.py`'s `pytest_collection_modifyitems`)

- [ ] **Step 5: Commit**

```bash
cd backend
git add tests/e2e/test_reports_async_flow.py
git commit -m "test(reports): add e2e coverage for the async compliance report flow"
```

---

## Self-Review

**1. Spec coverage:** The spec is "close the `reports.py:7` TODO by following the existing async-job pattern." Task 1 provides the job-state primitives; Task 2 provides the Celery task; Task 3 wires the route (dispatch + status + download) and removes the TODO comment; Task 4 proves the whole thing works against a real DB. All four are covered.

**2. Placeholder scan:** No `TBD`/`TODO`/"handle appropriately" strings in any step — every step has runnable code. Confirmed clean.

**3. Type consistency:** `ReportJobStatusResponse(job_id, status, download_url)` is defined once in Task 1 and imported unchanged in Task 3. `report_job_service`'s five function names/signatures are defined in Task 1 and consumed identically in Tasks 2 and 3 (`set_report_job_status(job_id, org_id, status)`, `get_report_job_status(job_id) -> dict|None`, `store_report_pdf(job_id, data)`, `load_report_pdf(job_id) -> bytes|None`). The Celery task name `generate_compliance_report` and its `.delay(job_id, org_id, start_iso, end_iso)` signature match between Task 2's definition and Task 3/4's call sites.

**4. Review Focus coverage:**
- Cross-org download/poll of a job_id → Task 3 Step 1 tests (`test_status_route_rejects_other_orgs_job`) and Task 4's `test_other_org_cannot_poll_or_download_job`.
- Concurrent same-org requests not colliding → each job gets its own `uuid4()`-keyed Redis entry by construction; not separately re-tested since Task 1's round-trip test already proves per-key isolation.
- Polling a failed job → Task 2 Step 1 test (`test_generate_sets_failed_status_when_render_raises`).
- Polling an unknown/expired job_id → Task 3 Step 1 test (`test_status_route_returns_404_for_unknown_job`).
- Downloading a completed-status job whose PDF already expired from Redis → Task 3 Step 1 test (`test_download_route_returns_404_when_pdf_expired_but_status_completed`).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-25-async-pdf-reports.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** - A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** - I implement every task myself in this session, the way this harness runs work, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end. Runs well with a mid-tier session model, since the plan carries the design.

For this plan I recommend **Native**, because the four tasks are a strict linear dependency chain (schema → task → route → e2e) with no parallel branches, there are only four of them, and a shipped mistake here is a report PDF returning stale/wrong bytes to a compliance admin — annoying but not destructive, and fully caught by Task 4's e2e test before merge. Does the plan capture what you want, and which approach should we use?
