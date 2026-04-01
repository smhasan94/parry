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


async def _resolve_org_from_clerk_jwt(
    token: str,
    db: AsyncSession,
) -> Org:
    """Verify a Clerk JWT and resolve the org from its claims."""
    from jose import JWTError, jwt

    from app.core.config import settings

    if not settings.clerk_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk authentication not configured",
        )

    try:
        # Clerk JWTs are signed with the secret key and use HS256
        payload = jwt.decode(
            token,
            settings.clerk_secret_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as e:
        log.warning("auth.clerk_jwt_invalid", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Clerk puts org info in the JWT claims
    clerk_org_id = payload.get("org_id")
    clerk_user_id = payload.get("sub")

    if clerk_org_id:
        # Look up org by Clerk org ID
        result = await db.execute(
            select(Org).where(Org.clerk_org_id == clerk_org_id, Org.is_active.is_(True))
        )
        org = result.scalar_one_or_none()
        if org:
            return org

    # Fallback: look up org by user's personal org (sub claim as clerk_org_id)
    if clerk_user_id:
        result = await db.execute(
            select(Org).where(Org.clerk_org_id == clerk_user_id, Org.is_active.is_(True))
        )
        org = result.scalar_one_or_none()
        if org:
            return org

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No organization found for this user. Create an org first.",
    )


async def get_current_org(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate via Authorization: Bearer <token>.

    Supports two token types:
    - Parry API key (sk-parry-...): hashed and looked up in api_keys table
    - Clerk JWT: verified and org resolved from clerk_org_id claim
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    # Parry API keys always start with sk-parry-
    if token.startswith("sk-parry-"):
        return await _resolve_org_from_api_key(token, db)

    # Otherwise treat as a Clerk JWT
    return await _resolve_org_from_clerk_jwt(token, db)


async def get_org_from_sdk_key(
    x_parry_secret: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate SDK requests via X-Parry-Secret: sk-parry-... header.

    Also updates last_used_at on the API key.
    """
    return await _resolve_org_from_api_key(x_parry_secret, db, update_last_used=True)
