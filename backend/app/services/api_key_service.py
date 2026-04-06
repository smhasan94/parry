import hashlib
import secrets
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import ApiKey

log = structlog.get_logger()

KEY_PREFIX = "sk-parry-"
KEY_BYTE_LENGTH = 32


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (raw_key, key_hash, key_prefix)."""
    random_part = secrets.token_urlsafe(KEY_BYTE_LENGTH)
    raw_key = f"{KEY_PREFIX}{random_part}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16]
    return raw_key, key_hash, key_prefix


async def create_api_key(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
) -> tuple[ApiKey, str]:
    """Create a new API key. Returns (api_key_model, raw_key).

    The raw key is only available at creation time.
    """
    raw_key, key_hash, key_prefix = generate_api_key()

    api_key = ApiKey(
        org_id=org_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    log.info("api_key.created", key_id=str(api_key.id), org_id=str(org_id), name=name)
    return api_key, raw_key


async def list_api_keys(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
) -> ApiKey:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == org_id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise NotFoundError("ApiKey", str(key_id))

    api_key.is_active = False
    await db.flush()
    await db.refresh(api_key)

    log.info("api_key.revoked", key_id=str(key_id), org_id=str(org_id))
    return api_key


async def resolve_org_from_key(
    db: AsyncSession,
    raw_key: str,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Resolve org_id from a raw API key. Returns (org_id, key_id) or None."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None
    return api_key.org_id, api_key.id
