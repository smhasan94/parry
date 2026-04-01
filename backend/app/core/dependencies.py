import hashlib
import hmac
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Org
from app.db.session import get_db

log = structlog.get_logger()


async def get_current_org(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate via API key in Authorization header.

    Expected format: Bearer sk-parry-...
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = authorization.removeprefix("Bearer ").strip()
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


async def verify_internal_secret(
    x_parry_secret: Annotated[str, Header()],
) -> None:
    """Verify SDK-to-backend internal secret for event ingestion."""
    from app.core.config import settings

    if not hmac.compare_digest(x_parry_secret, settings.parry_internal_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal secret",
        )
