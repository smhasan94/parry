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
