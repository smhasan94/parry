import hashlib
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Org
from app.db.session import get_db

log = structlog.get_logger()


async def _resolve_org_from_api_key(
    raw_key: str,
    db: AsyncSession,
    update_last_used: bool = False,
) -> Org:
    """Common logic: hash the key, look up ApiKey, resolve Org."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    if update_last_used:
        api_key.last_used_at = datetime.now(timezone.utc)

    result = await db.execute(
        select(Org).where(Org.id == api_key.org_id, Org.is_active.is_(True))
    )
    org = result.scalar_one_or_none()

    if org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization not found or inactive",
        )

    return org


async def get_current_org(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate dashboard requests via Authorization: Bearer sk-parry-..."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = authorization.removeprefix("Bearer ").strip()
    return await _resolve_org_from_api_key(raw_key, db)


async def get_org_from_sdk_key(
    x_parry_secret: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate SDK requests via X-Parry-Secret: sk-parry-... header.

    Also updates last_used_at on the API key.
    """
    return await _resolve_org_from_api_key(x_parry_secret, db, update_last_used=True)
