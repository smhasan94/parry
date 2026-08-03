"""Storage and retrieval of third-party probe credentials.

The plaintext token enters through ``create``/``rotate_secret`` and
leaves only through ``reveal_secret``, immediately before an outbound
call. It is never held on the model, returned in a schema, or logged.

Connection config is validated here rather than at sync time. The worker
will fetch whatever host is stored, with a token attached — so a host
that would be an SSRF target must be rejected on the way in, when a
person is present to see the error, rather than discovered later by a
background task.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secret_crypto
from app.core.exceptions import NotFoundError
from app.db.models import ProbeCredential
from app.discovery.okta import resolve_base_url

log = structlog.get_logger()


def _validate_config(provider: str, config: dict[str, Any]) -> None:
    if provider == "okta":
        domain = config.get("okta_domain")
        if not domain:
            raise ValueError("okta credentials require config.okta_domain")
        # Raises OktaDomainError (a ValueError) for anything outside the
        # Okta allowlist — same guard the interactive sync route uses.
        resolve_base_url(domain)


async def create(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    probe_type: str,
    provider: str,
    label: str,
    secret: str,
    config: dict[str, Any] | None = None,
) -> ProbeCredential:
    config = config or {}
    _validate_config(provider, config)

    credential = ProbeCredential(
        org_id=org_id,
        probe_type=probe_type,
        provider=provider,
        label=label,
        config=config,
        # Raises ConfigurationError when no key is set, rather than
        # persisting the token in the clear.
        encrypted_secret=secret_crypto.encrypt_secret(secret),
        is_active=True,
    )
    db.add(credential)
    await db.flush()

    log.info(
        "probe_credential.created",
        org_id=str(org_id),
        credential_id=str(credential.id),
        provider=provider,
    )
    return credential


async def list_for_org(db: AsyncSession, *, org_id: uuid.UUID) -> list[ProbeCredential]:
    result = await db.execute(
        select(ProbeCredential)
        .where(ProbeCredential.org_id == org_id)
        .order_by(ProbeCredential.created_at.desc())
    )
    return list(result.scalars().all())


async def get(db: AsyncSession, *, org_id: uuid.UUID, credential_id: uuid.UUID) -> ProbeCredential:
    result = await db.execute(
        select(ProbeCredential).where(
            ProbeCredential.id == credential_id,
            ProbeCredential.org_id == org_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise NotFoundError("ProbeCredential", str(credential_id))
    return credential


async def rotate_secret(
    db: AsyncSession, *, org_id: uuid.UUID, credential_id: uuid.UUID, secret: str
) -> ProbeCredential:
    credential = await get(db, org_id=org_id, credential_id=credential_id)
    credential.encrypted_secret = secret_crypto.encrypt_secret(secret)
    await db.flush()
    log.info("probe_credential.rotated", credential_id=str(credential_id))
    return credential


async def delete(db: AsyncSession, *, org_id: uuid.UUID, credential_id: uuid.UUID) -> None:
    credential = await get(db, org_id=org_id, credential_id=credential_id)
    await db.delete(credential)
    await db.flush()
    log.info("probe_credential.deleted", credential_id=str(credential_id))


async def list_due_for_sync(db: AsyncSession) -> list[ProbeCredential]:
    """Credentials the scheduled worker should sync.

    Cross-org by design — this is the worker's view, not a tenant's.
    Disabled credentials are skipped so an operator can stop a noisy or
    failing integration without deleting it and losing the token.
    """
    result = await db.execute(select(ProbeCredential).where(ProbeCredential.is_active.is_(True)))
    return list(result.scalars().all())


async def record_sync(
    db: AsyncSession,
    credential: ProbeCredential,
    *,
    status: str,
    error: str | None = None,
) -> ProbeCredential:
    """Record the outcome so a broken integration is visible.

    Without this a revoked token fails silently every night and the
    register quietly goes stale — which looks identical to "no new AI
    was found".
    """
    credential.last_sync_at = datetime.now(tz=UTC)
    credential.last_sync_status = status
    credential.last_sync_error = error
    await db.flush()
    return credential


def reveal_secret(credential: ProbeCredential) -> str:
    """Decrypt for immediate use in an outbound call. Do not persist."""
    return secret_crypto.decrypt_secret(credential.encrypted_secret)
