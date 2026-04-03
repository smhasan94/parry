"""Async SDK client for Parry — use in async codebases (FastAPI, aiohttp, etc.)."""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("parry")


class AsyncParryClient:
    """Async version of ParryClient. Sends events without blocking the event loop."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.parry.dev",
        default_agent_id: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_agent_id = default_agent_id
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-Parry-Secret": api_key,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def send_event(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        prompt: str | None = None,
        response: str | None = None,
        model: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        latency_ms: int | None = None,
        token_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send an event to Parry backend. Fire-and-forget via background task."""
        resolved_agent_id = agent_id or self.default_agent_id
        if not resolved_agent_id:
            logger.warning("parry: no agent_id provided, skipping event")
            return

        payload = {
            "agent_id": resolved_agent_id,
            "session_id": session_id,
            "prompt": _truncate(prompt, 4000),
            "response": _truncate(response, 4000),
            "model": model,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "token_count": token_count,
            "metadata": metadata,
        }

        # Fire-and-forget — schedule as background task, never block caller
        asyncio.create_task(self._send(payload))

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            resp = await self._http.post("/api/v1/events/ingest", json=payload)
            if resp.status_code >= 400:
                logger.warning("parry: event rejected (%s): %s", resp.status_code, resp.text[:200])
        except Exception:
            logger.warning("parry: failed to send event, backend unreachable", exc_info=True)

    async def send_event_blocking(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        prompt: str | None = None,
        response: str | None = None,
        model: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        latency_ms: int | None = None,
        token_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send an event and wait for confirmation. Use when you need delivery guarantees."""
        resolved_agent_id = agent_id or self.default_agent_id
        if not resolved_agent_id:
            logger.warning("parry: no agent_id provided, skipping event")
            return

        payload = {
            "agent_id": resolved_agent_id,
            "session_id": session_id,
            "prompt": _truncate(prompt, 4000),
            "response": _truncate(response, 4000),
            "model": model,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "token_count": token_count,
            "metadata": metadata,
        }

        await self._send(payload)

    async def close(self) -> None:
        await self._http.aclose()


def _truncate(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    return text[:max_len] if len(text) > max_len else text
