"""Redis pubsub fan-out for live dashboard events.

Both the blocking proxy check and the dashboard SSE endpoint talk to
the same ``org:{org_id}:events`` channel. Publishing is fire-and-forget
and MUST never raise — a Redis blip can't be allowed to affect the
blocking response path. Subscribers receive parsed JSON dicts and are
responsible for applying any per-connection filters.

Payloads are intentionally small (no raw prompts — 200-char preview
only) so the pubsub buffer stays cheap and no sensitive content leaks
across the wire beyond what's already shown in the dashboard.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger()

CHANNEL_PATTERN = "org:{org_id}:events"
PROMPT_PREVIEW_CHARS = 200


def channel_for(org_id: str) -> str:
    return CHANNEL_PATTERN.format(org_id=org_id)


def publish_blocked_event(
    org_id: str,
    *,
    detector: str,
    reason: str,
    severity: str,
    confidence: float,
    prompt: str | None,
    model: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Fire-and-forget pubsub write. Swallows every failure mode."""
    try:
        from app.core.redis_pool import sync_redis_raw

        payload = {
            "type": "blocked",
            "org_id": org_id,
            "detector": detector,
            "reason": reason,
            "severity": severity,
            "confidence": confidence,
            "prompt_preview": (prompt or "")[:PROMPT_PREVIEW_CHARS],
            "model": model,
            "agent_id": agent_id,
            "ts": datetime.now(UTC).isoformat(),
        }
        client = sync_redis_raw()
        client.publish(channel_for(org_id), json.dumps(payload))
    except Exception:
        # Never block the blocking path on a Redis hiccup.
        log.debug("event_bus.publish_failed", exc_info=True)


async def subscribe(org_id: str) -> AsyncIterator[dict[str, Any]]:
    """Async iterator over pubsub messages for an org.

    Yields decoded JSON dicts. On Redis errors the iterator ends
    cleanly so the SSE handler can emit a final keepalive and close.
    """
    try:
        from app.core.redis_pool import async_redis
    except Exception:  # pragma: no cover
        log.debug("event_bus.redis_asyncio_unavailable", exc_info=True)
        return

    client = async_redis()
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(channel_for(org_id))
        async for message in pubsub.listen():
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    except Exception:
        log.debug("event_bus.subscribe_error", exc_info=True)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel_for(org_id))
            await pubsub.close()
        with contextlib.suppress(Exception):
            await client.close()
