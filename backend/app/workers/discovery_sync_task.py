"""Scheduled discovery: re-sync every stored probe credential.

Turns discovery from a snapshot into a monitor. Without this the register
reflects whenever someone last clicked sync, and a tool adopted the day
after never appears.

Runs unattended across every tenant, so the design point is failure
isolation: one org's revoked token must not stop everyone else's sync,
and every outcome is recorded on the credential so a broken integration
is visible instead of looking like "nothing new was found".
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfigurationError
from app.core.secret_crypto import DecryptionError, is_configured
from app.db.models import ProbeCredential
from app.db.session import make_task_session_factory
from app.discovery.okta import (
    OktaDomainError,
    fetch_okta_apps_and_users,
    parse_okta_response,
)
from app.discovery.sso_probe import SSOProbeProcessor
from app.services import probe_credential_service as creds
from app.workers.celery_app import celery_app

log = structlog.get_logger()

# Recorded on the credential and shown to operators, so keep it short and
# free of anything sensitive.
_MAX_ERROR = 500


def _safe_error(exc: Exception, secret: str | None) -> str:
    """Summarize a failure without leaking the credential.

    httpx errors can embed the request, and a provider's message can echo
    back what was sent, so the token is redacted defensively even though
    it should never appear here.
    """
    message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR]
    if secret:
        message = message.replace(secret, "<redacted>")
    return message


async def sync_one_credential(db: AsyncSession, credential: ProbeCredential) -> dict[str, Any]:
    """Run one credential's probe and record the outcome.

    Never raises: the caller is iterating over every tenant, and one bad
    row must not end the run.
    """
    secret: str | None = None
    try:
        secret = creds.reveal_secret(credential)
        raw = await fetch_okta_apps_and_users(
            okta_domain=credential.config["okta_domain"], api_token=secret
        )
        processor = await SSOProbeProcessor.create(db)
        result = await processor.process_events(
            db=db, org_id=credential.org_id, events=parse_okta_response(raw)
        )
        await creds.record_sync(db, credential, status="ok", error=None)

        log.info(
            "discovery_sync.ok",
            credential_id=str(credential.id),
            org_id=str(credential.org_id),
            processed=result.processed,
            created=result.created,
            matched=result.matched,
        )
        return {
            "status": "ok",
            "credential_id": str(credential.id),
            "processed": result.processed,
            "created": result.created,
            "matched": result.matched,
        }

    except (
        httpx.HTTPError,
        OktaDomainError,
        DecryptionError,
        ConfigurationError,
        KeyError,
    ) as exc:
        error = _safe_error(exc, secret)
        await creds.record_sync(db, credential, status="failed", error=error)
        log.warning(
            "discovery_sync.failed",
            credential_id=str(credential.id),
            org_id=str(credential.org_id),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "credential_id": str(credential.id), "error": error}


async def sync_all_credentials(db: AsyncSession) -> dict[str, Any]:
    """Sync every active credential, one tenant's failure at a time."""
    if not is_configured():
        # Nothing can be decrypted, so every credential would fail
        # identically. Say so once instead of once per row.
        log.warning("discovery_sync.skipped_no_encryption_key")
        return {"synced": 0, "failed": 0, "skipped": "no_encryption_key"}

    credentials = await creds.list_due_for_sync(db)
    synced = failed = 0

    for credential in credentials:
        outcome = await sync_one_credential(db, credential)
        if outcome["status"] == "ok":
            synced += 1
        else:
            failed += 1
        # Commit per credential so one tenant's failure cannot roll back
        # another tenant's discovered systems.
        await db.commit()

    log.info("discovery_sync.complete", synced=synced, failed=failed)
    return {"synced": synced, "failed": failed, "total": len(credentials)}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="sync_discovery_probes",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    soft_time_limit=600,
    time_limit=900,
)
def sync_discovery_probes(self: Any) -> dict[str, Any]:
    """Celery entrypoint for the scheduled discovery sweep."""
    try:
        return asyncio.run(_run())
    except Exception:
        log.error(
            "discovery_sync.task_failed",
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _run() -> dict[str, Any]:
    factory = make_task_session_factory()
    engine = factory.kw["bind"]
    try:
        async with factory() as db:
            return await sync_all_credentials(db)
    finally:
        await engine.dispose()
