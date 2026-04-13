"""Shared Redis connection pools.

Every module that needs Redis should import from here instead of calling
Redis.from_url() ad hoc. This gives us:
  - Connection pooling (reuse sockets instead of connect-per-call)
  - A single place to tune pool size, timeouts, and retry policy
  - Clean shutdown via close_pools() in the app lifespan

Two pools are exposed:
  - sync_redis()  — for sync contexts (Celery tasks, event_bus publish, middleware)
  - async_redis() — for async contexts (SSE subscribers, async services)
"""

from __future__ import annotations

import redis as sync_redis_lib
import redis.asyncio as async_redis_lib
import structlog

from app.core.config import settings

log = structlog.get_logger()

# ── Sync pool (used by rate limiter, event bus publish, Celery tasks) ──

_sync_pool: sync_redis_lib.ConnectionPool | None = None


def _get_sync_pool() -> sync_redis_lib.ConnectionPool:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = sync_redis_lib.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
    return _sync_pool


def sync_redis() -> sync_redis_lib.Redis:
    """Get a sync Redis client backed by the shared connection pool."""
    return sync_redis_lib.Redis(connection_pool=_get_sync_pool())


# ── Async pool (used by SSE subscribers, async service methods) ──

_async_pool: async_redis_lib.ConnectionPool | None = None


def _get_async_pool() -> async_redis_lib.ConnectionPool:
    global _async_pool
    if _async_pool is None:
        _async_pool = async_redis_lib.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
    return _async_pool


def async_redis() -> async_redis_lib.Redis:
    """Get an async Redis client backed by the shared connection pool."""
    return async_redis_lib.Redis(connection_pool=_get_async_pool())


# ── Raw bytes pool (for pubsub publish where decode_responses=False) ──

_sync_raw_pool: sync_redis_lib.ConnectionPool | None = None


def _get_sync_raw_pool() -> sync_redis_lib.ConnectionPool:
    global _sync_raw_pool
    if _sync_raw_pool is None:
        _sync_raw_pool = sync_redis_lib.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=5,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=False,
        )
    return _sync_raw_pool


def sync_redis_raw() -> sync_redis_lib.Redis:
    """Get a sync Redis client that returns raw bytes (for pubsub publish)."""
    return sync_redis_lib.Redis(connection_pool=_get_sync_raw_pool())


# ── Cleanup ──


async def close_pools() -> None:
    """Close all connection pools. Called from app lifespan shutdown."""
    global _sync_pool, _async_pool, _sync_raw_pool

    if _async_pool is not None:
        await _async_pool.disconnect()
        _async_pool = None

    if _sync_pool is not None:
        _sync_pool.disconnect()
        _sync_pool = None

    if _sync_raw_pool is not None:
        _sync_raw_pool.disconnect()
        _sync_raw_pool = None

    log.info("redis.pools_closed")
