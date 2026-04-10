"""Redis-backed rate limiting middleware for FastAPI."""

import time
from typing import Any

import structlog
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import settings

log = structlog.get_logger()

# Rate limits per endpoint pattern (requests per minute)
RATE_LIMITS: dict[str, int] = {
    "/api/v1/events/ingest": 300,  # SDK ingestion — high volume
    "/api/v1/events": 60,  # Event listing
    "/api/v1/agents": 60,
    "/api/v1/incidents": 60,
    # Regression simulation endpoints — expensive (full event scan).
    # Listed BEFORE the broader /policies prefix so they win the
    # longest-match in `_get_limit_for_path`.
    "/api/v1/policies/simulate": 10,
    "/api/v1/custom-rules/simulate": 10,
    # Red-team runs are expensive — full corpus replay through the
    # detection pipeline. 5/hour per client is plenty for sales demos
    # and weekly regression checks; anything more is abuse.
    "/api/v1/red-team/runs": 5,
    "/api/v1/red-team": 30,
    # MCP SDK-runtime paths. Connections are rare (once per agent
    # start), so 30/min is plenty. Dashboard reads under /mcp/servers
    # get the default 60/min via fallthrough.
    "/api/v1/mcp/connections": 30,
    "/api/v1/mcp/events": 300,
    "/api/v1/mcp": 60,
    "/api/v1/compliance/auditor-bundle": 5,
    "/api/v1/compliance": 30,
    "/api/v1/threat-intel": 30,
    "/api/v1/permissions": 30,
    "/api/v1/budgets": 30,
    "/api/v1/policies": 60,
    "/api/v1/custom-rules": 60,
    "/api/v1/api-keys": 30,
    "/api/v1/billing": 20,
    "/api/v1/webhooks": 100,  # Webhooks from external services
    # SSO flow is unauthenticated (anyone can kick off a SAML login
    # for any org they can name) and each POST burns a WorkOS API
    # call plus an org lookup. 10/min per client is plenty for real
    # users and shuts down script-kiddie enumeration.
    "/api/v1/sso/session": 10,
    "/api/v1/sso/login": 10,
    "/api/v1/sso/callback": 20,
}

DEFAULT_LIMIT = 60  # requests per minute


def _get_limit_for_path(path: str) -> int:
    """Find the most specific rate limit for a request path."""
    for prefix, limit in RATE_LIMITS.items():
        if path.startswith(prefix):
            return limit
    return DEFAULT_LIMIT


def _get_client_key(request: Request) -> str:
    """Extract a client identifier for rate limiting."""
    # Use API key prefix if present, otherwise IP
    sdk_key = request.headers.get("x-parry-secret", "")
    if sdk_key:
        return f"ratelimit:key:{sdk_key[:14]}"

    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer sk-parry-"):
        return f"ratelimit:key:{auth[7:21]}"

    # Fall back to client IP
    client_ip = request.client.host if request.client else "unknown"
    return f"ratelimit:ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter using Redis."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._redis = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            import redis

            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Skip if Redis is unavailable (fail open)
        try:
            r = self._get_redis()
            client_key = _get_client_key(request)
            limit = _get_limit_for_path(request.url.path)
            window = 60  # 1 minute window

            key = f"{client_key}:{request.url.path.split('?')[0]}"
            now = time.time()

            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window)
            results = pipe.execute()

            request_count = results[2]

            if request_count > limit:
                log.warning(
                    "rate_limit.exceeded",
                    client=client_key,
                    path=request.url.path,
                    count=request_count,
                    limit=limit,
                )
                # BaseHTTPMiddleware can't rely on the FastAPI
                # exception handlers — raising HTTPException here
                # escapes as an unhandled error and Starlette
                # converts it to 500. Return a Response directly.
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={
                        "Retry-After": str(window),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - request_count))
            return response

        except Exception:
            # Fail open — if Redis is down, don't block requests.
            # There's no HTTPException branch here anymore because
            # the 429 path returns a JSONResponse directly above.
            log.debug("rate_limit.redis_unavailable", exc_info=True)
            return await call_next(request)
