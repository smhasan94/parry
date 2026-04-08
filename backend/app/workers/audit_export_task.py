"""Monthly SOC 2 audit log export to S3.

Runs on the 1st of every month at 02:00 UTC. For each active org,
exports the previous calendar month's audit trail as a tamper-evident
JSON artefact and uploads it to the configured bucket at:

    s3://{bucket}/{prefix}/org={org_id}/YYYY/MM/audit-YYYY-MM.json

The task is a no-op when ``audit_export_s3_bucket`` is unset — orgs
that don't need SOC 2 artefacts don't pay for them. boto3 is
imported lazily so the backend still starts on machines without the
dep installed.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="export_audit_log_monthly",
    soft_time_limit=1800,
    time_limit=1860,
)
def export_audit_log_monthly() -> dict[str, int]:
    return asyncio.run(_export_audit_log_monthly())


def _previous_month_range(now: datetime) -> tuple[datetime, datetime, str]:
    """Return ``(start, end, label)`` for the full previous calendar month.

    ``start`` is inclusive, ``end`` is exclusive — same convention as
    ``audit_export_service.export_audit_log``. ``label`` is the
    ``YYYY-MM`` string used in the S3 object key.
    """
    year = now.year
    month = now.month - 1
    if month == 0:
        month = 12
        year -= 1
    start = datetime(year, month, 1, tzinfo=UTC)
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    end = datetime(next_year, next_month, 1, tzinfo=UTC)
    label = f"{year:04d}-{month:02d}"
    return start, end, label


async def _export_audit_log_monthly() -> dict[str, int]:
    from app.core import on_prem
    from app.core.config import settings
    from app.db.models import Org
    from app.db.session import make_task_session_factory
    from app.services import audit_export_service, audit_service

    if on_prem.is_on_prem():
        # On-prem deployments generate audit exports via the admin
        # route, not S3 upload — the box is air-gapped.
        log.info("audit.export_skipped_on_prem")
        return {"exported": 0, "skipped": 0, "errored": 0}

    if not settings.audit_export_s3_bucket:
        log.info("audit.export_s3_disabled")
        return {"exported": 0, "skipped": 0, "errored": 0}

    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        log.warning("audit.export_boto3_missing")
        return {"exported": 0, "skipped": 0, "errored": 0}

    s3 = boto3.client(
        "s3",
        region_name=settings.audit_export_s3_region,
        aws_access_key_id=settings.audit_export_aws_access_key_id or None,
        aws_secret_access_key=settings.audit_export_aws_secret_access_key or None,
    )

    now = datetime.now(UTC)
    start, end, label = _previous_month_range(now)
    year_str, month_str = label.split("-")

    exported = 0
    skipped = 0
    errored = 0

    # Disposable per-task engine — see make_task_session_factory
    # docstring for the "Task attached to a different loop" story.
    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            orgs = (
                (await db.execute(select(Org).where(Org.is_active.is_(True))))
                .scalars()
                .all()
            )

            for org in orgs:
                try:
                    body, count, final_hash = await audit_export_service.export_audit_log(
                        db,
                        org.id,
                        start=start,
                        end=end,
                        fmt="json",
                        generated_at=now,
                    )
                    if count == 0:
                        skipped += 1
                        continue

                    key = (
                        f"{settings.audit_export_s3_prefix.strip('/')}/"
                        f"org={org.id}/{year_str}/{month_str}/audit-{label}.json"
                    )
                    s3.put_object(
                        Bucket=settings.audit_export_s3_bucket,
                        Key=key,
                        Body=body,
                        ContentType="application/json",
                        ServerSideEncryption="AES256",
                        Metadata={
                            "parry-chain-tip": final_hash,
                            "parry-entry-count": str(count),
                            "parry-period": label,
                        },
                    )

                    await audit_service.log_action(
                        db,
                        org_id=org.id,
                        action="audit_log.exported",
                        actor_type="system",
                        actor_label="audit-export-task",
                        resource_type="audit_log_export",
                        details={
                            "period": label,
                            "format": "json",
                            "entry_count": count,
                            "final_row_hash": final_hash,
                            "s3_bucket": settings.audit_export_s3_bucket,
                            "s3_key": key,
                        },
                    )
                    await db.commit()
                    exported += 1
                    log.info(
                        "audit.exported_to_s3",
                        org_id=str(org.id),
                        period=label,
                        entry_count=count,
                        s3_key=key,
                    )
                except Exception:
                    errored += 1
                    await db.rollback()
                    log.error(
                        "audit.export_failed",
                        org_id=str(org.id),
                        period=label,
                        exc_info=True,
                    )
    finally:
        await task_engine.dispose()

    log.info(
        "audit.export_run_complete",
        period=label,
        exported=exported,
        skipped=skipped,
        errored=errored,
    )
    return {"exported": exported, "skipped": skipped, "errored": errored}
