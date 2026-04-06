"""Redis-backed rate limiting middleware for FastAPI."""

import time
from typing import Any

import structlog
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings

log = structlog.get_logger()

# Rate limits per endpoint pattern (requests per minute)
RATE_LIMITS: dict[str, int] = {
    "/api/v1/events/ingest": 300,  # SDK ingestion — high volume
    "/api/v1/events": 60,  # Event listing
    "/api/v1/agents": 60,
    "/api/v1/incidents": 60,
    "/api/v1/policies": 60,
    "/api/v1/api-keys": 30,
    "/api/v1/billing": 20,
    "/api/v1/webhooks": 100,  # Webhooks from external services
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
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Try again later.",
                    headers={"Retry-After": str(window)},
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - request_count))
            return response

        except HTTPException:
            raise
        except Exception:
            # Fail open — if Redis is down, don't block requests
            log.debug("rate_limit.redis_unavailable", exc_info=True)
            return await call_next(request)
