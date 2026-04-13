import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
import structlog
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Org
from app.db.session import get_db

log = structlog.get_logger()


@dataclass
class Actor:
    """Identity of the entity performing an action.

    actor_type: 'user' (Clerk JWT), 'api_key' (sk-parry-...), or 'system'
    actor_id:   Clerk user ID, ApiKey UUID (str), or None
    label:      human-friendly display name (email, key name, etc.)
    clerk_role: raw Clerk org role claim (e.g. "org:admin"); None for
                non-Clerk actors or when the JWT omits org context.
                Resolved into a Role enum by app.core.rbac.actor_role.
    """

    actor_type: str
    actor_id: str | None = None
    label: str | None = None
    clerk_role: str | None = None


# Cache JWKS keys in memory (refreshed on cache miss)
_jwks_cache: dict[str, Any] | None = None


async def _get_clerk_jwks() -> dict[str, Any]:
    """Fetch Clerk's JWKS from their well-known endpoint."""
    global _jwks_cache

    # Derive the Clerk Frontend API URL from the publishable key
    # pk_test_xxx... or pk_live_xxx... -> the domain is encoded in the key
    # But easier: Clerk JWKS is at https://<clerk-domain>/.well-known/jwks.json
    # The clerk_publishable_key contains the Clerk Frontend API domain (base64 after pk_test_)
    import base64

    from app.core.config import settings

    try:
        # Clerk publishable key format: pk_test_<base64-encoded-frontend-api>
        key_parts = settings.clerk_publishable_key.split("_", 2)
        encoded = key_parts[2] if len(key_parts) > 2 else ""
        # Add padding
        padded = encoded + "=" * (4 - len(encoded) % 4)
        frontend_api = base64.b64decode(padded).decode("utf-8").rstrip("$")
    except Exception:
        frontend_api = ""

    if not frontend_api:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot derive Clerk JWKS URL from publishable key",
        )

    jwks_url = f"https://{frontend_api}/.well-known/jwks.json"

    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_url, timeout=5.0)
        resp.raise_for_status()
        _jwks_cache = resp.json()

    return _jwks_cache


async def _resolve_from_api_key(
    raw_key: str,
    db: AsyncSession,
    update_last_used: bool = False,
) -> tuple[Org, Actor]:
    """Common logic: hash the key, look up ApiKey, resolve Org and Actor."""
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
        api_key.last_used_at = datetime.now(UTC)

    org_result = await db.execute(
        select(Org).where(Org.id == api_key.org_id, Org.is_active.is_(True))
    )
    org = org_result.scalar_one_or_none()

    if org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization not found or inactive",
        )

    actor = Actor(actor_type="api_key", actor_id=str(api_key.id), label=api_key.name)
    return org, actor


async def _resolve_org_from_api_key(
    raw_key: str,
    db: AsyncSession,
    update_last_used: bool = False,
) -> Org:
    """Backward-compat shim returning just the Org."""
    org, _ = await _resolve_from_api_key(raw_key, db, update_last_used)
    return org


async def _resolve_from_clerk_jwt(
    token: str,
    db: AsyncSession,
) -> tuple[Org, Actor]:
    """Verify a Clerk JWT and resolve both Org and Actor from its claims."""
    org = await _resolve_org_from_clerk_jwt(token, db)
    # Re-decode payload to extract user info (cached JWKS makes this cheap)
    try:
        jwks = _jwks_cache or await _get_clerk_jwks()
        payload = jwt.decode(token, jwks, algorithms=["RS256"], options={"verify_aud": False})
    except (JWTError, httpx.HTTPError):
        payload = {}

    user_id = payload.get("sub")
    email = payload.get("email") or payload.get("primary_email_address")
    label = email or user_id
    # Clerk puts the org role in `org_role` when the JWT was issued with
    # an active org context. Missing claim → None → defaults to VIEWER
    # in rbac.actor_role, which is the secure default.
    clerk_role = payload.get("org_role")

    # Demo mode: if Clerk didn't issue an org role AND this is the only
    # active org in the DB (single-org self-hosted deployment), treat
    # the user as owner so they aren't locked out of their own instance.
    if not clerk_role:
        count_result = await db.execute(select(Org.id).where(Org.is_active.is_(True)))
        if len(list(count_result.scalars().all())) == 1:
            clerk_role = "org:owner"

    actor = Actor(
        actor_type="user",
        actor_id=user_id,
        label=label,
        clerk_role=clerk_role,
    )
    return org, actor


async def _resolve_org_from_clerk_jwt(
    token: str,
    db: AsyncSession,
) -> Org:
    """Verify a Clerk JWT (RS256 via JWKS) and resolve the org from its claims."""
    global _jwks_cache

    try:
        # Try cached JWKS first, refresh on failure
        jwks = _jwks_cache or await _get_clerk_jwks()

        try:
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except JWTError:
            # JWKS might be stale — refresh and retry once
            jwks = await _get_clerk_jwks()
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
    except JWTError as e:
        log.warning("auth.clerk_jwt_invalid", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from e
    except httpx.HTTPError as e:
        log.error("auth.clerk_jwks_fetch_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify token — could not reach auth provider",
        ) from e

    # Clerk puts org info in the JWT claims
    clerk_org_id = payload.get("org_id")
    clerk_user_id = payload.get("sub")

    if clerk_org_id:
        result = await db.execute(
            select(Org).where(Org.clerk_org_id == clerk_org_id, Org.is_active.is_(True))
        )
        org = result.scalar_one_or_none()
        if org:
            return org

    # Fallback: match on user ID (personal org / demo setup)
    if clerk_user_id:
        result = await db.execute(
            select(Org).where(Org.clerk_org_id == clerk_user_id, Org.is_active.is_(True))
        )
        org = result.scalar_one_or_none()
        if org:
            return org

    # Last resort: if there's exactly one org (demo mode), use it
    result = await db.execute(select(Org).where(Org.is_active.is_(True)))
    orgs = list(result.scalars().all())
    if len(orgs) == 1:
        log.info("auth.demo_mode_fallback", clerk_user_id=clerk_user_id, org_id=str(orgs[0].id))
        return orgs[0]

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No organization found for this user.",
    )


async def get_current_org(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Org:
    """Authenticate via Authorization: Bearer <token>.

    Supports two token types:
    - Parry API key (sk-parry-...): hashed and looked up in api_keys table
    - Clerk JWT: verified via JWKS (RS256) and org resolved from claims
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


async def get_current_actor(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> tuple[Org, Actor]:
    """Like get_current_org but also returns the Actor identity for audit logging."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    if token.startswith("sk-parry-"):
        return await _resolve_from_api_key(token, db)

    return await _resolve_from_clerk_jwt(token, db)
