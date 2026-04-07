"""LlamaIndex callback handler for Parry.

Hooks into LlamaIndex's CBEventType.LLM lifecycle. The BaseCallbackHandler
class is imported lazily inside __init__ so this module is safe to
import without llama-index-core installed.

Usage:
    from llama_index.core import Settings
    from parry.wrappers.llamaindex import ParryCallbackHandler

    Settings.callback_manager.add_handler(
        ParryCallbackHandler(agent_id="my-llamaindex-agent")
    )

Fail-open: any exception inside intercept_completion is swallowed so
the LlamaIndex run cannot be broken by a Parry-side error.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")


def _base_handler_class() -> type:
    try:
        from llama_index.core.callbacks.base_handler import (  # type: ignore
            BaseCallbackHandler,
        )
    except ImportError as e:
        raise ImportError(
            "llama-index-core not installed. Install with: pip install parry[llamaindex]"
        ) from e
    return BaseCallbackHandler


def _llm_event_type() -> Any:
    from llama_index.core.callbacks.schema import CBEventType  # type: ignore

    return CBEventType.LLM


def _extract_prompt(payload: dict | None) -> str | None:
    if not payload:
        return None
    # LlamaIndex payload keys vary by version: "messages", "prompt", "formatted_prompt"
    for key in ("formatted_prompt", "prompt"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        last = messages[-1]
        content = getattr(last, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(last, dict):
            c = last.get("content")
            if isinstance(c, str):
                return c
    return None


def _extract_response(payload: dict | None) -> tuple[str | None, int | None, str | None]:
    """Returns (response_text, token_count, model)."""
    if not payload:
        return None, None, None
    # Newer LlamaIndex puts a ChatResponse under "response"
    response_obj = payload.get("response")
    text: str | None = None
    model: str | None = None
    tokens: int | None = None

    if response_obj is not None:
        # Try .message.content (ChatResponse)
        msg = getattr(response_obj, "message", None)
        if msg is not None:
            text = getattr(msg, "content", None)
        if text is None:
            text = getattr(response_obj, "text", None)

        # Token usage may live on response_obj.raw.usage
        raw = getattr(response_obj, "raw", None)
        if raw is not None:
            usage = getattr(raw, "usage", None) or (
                raw.get("usage") if isinstance(raw, dict) else None
            )
            if usage is not None:
                tokens = (
                    getattr(usage, "total_tokens", None)
                    or (usage.get("total_tokens") if isinstance(usage, dict) else None)
                )
        model = getattr(response_obj, "model", None)

    if text is None:
        # Fallback: plain string in payload
        val = payload.get("response")
        if isinstance(val, str):
            text = val

    # Model may also be in the payload root
    if model is None:
        model = payload.get("model") or payload.get("serialized", {}).get("model") if isinstance(
            payload.get("serialized"), dict
        ) else None

    return text, tokens, model


def ParryCallbackHandler(  # noqa: N802  — factory exposes a class name to users
    agent_id: str | None = None,
    session_id: str | None = None,
):
    """Factory for a BaseCallbackHandler subclass with Parry instrumentation.

    Factory pattern matches ParryConversableAgent: the BaseCallbackHandler
    superclass must be imported lazily so this module works without
    llama-index-core installed.
    """
    base = _base_handler_class()
    llm_event = _llm_event_type()

    class _ParryLlamaHandler(base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(
                event_starts_to_ignore=[],
                event_ends_to_ignore=[],
            )
            self._agent_id = agent_id
            self._session_id = session_id
            self._runs: dict[str, tuple[float, str | None]] = {}

        def start_trace(self, trace_id: str | None = None) -> None:  # noqa: D401
            """Called at the start of a top-level trace — nothing to do."""

        def end_trace(
            self,
            trace_id: str | None = None,
            trace_map: dict | None = None,
        ) -> None:
            """Called at the end of a top-level trace — nothing to do."""

        def on_event_start(
            self,
            event_type: Any,
            payload: dict | None = None,
            event_id: str = "",
            parent_id: str = "",
            **kwargs: Any,
        ) -> str:
            if event_type == llm_event:
                self._runs[event_id] = (time.monotonic(), _extract_prompt(payload))
            return event_id

        def on_event_end(
            self,
            event_type: Any,
            payload: dict | None = None,
            event_id: str = "",
            **kwargs: Any,
        ) -> None:
            if event_type != llm_event:
                return

            start, prompt = self._runs.pop(event_id, (time.monotonic(), None))
            latency_ms = int((time.monotonic() - start) * 1000)
            response_text, token_count, model = _extract_response(payload)

            try:
                intercept_completion(
                    prompt=prompt,
                    response=response_text,
                    model=model,
                    tool_calls=None,
                    token_count=token_count,
                    latency_ms=latency_ms,
                    agent_id=self._agent_id,
                    session_id=self._session_id,
                )
            except Exception:
                logger.warning("parry.llamaindex.intercept_failed", exc_info=True)

    return _ParryLlamaHandler()
