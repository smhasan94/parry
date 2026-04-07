"""AutoGen ConversableAgent wrapper for Parry.

Subclasses autogen's ConversableAgent and overrides generate_reply
to wrap every model call with timing + intercept_completion. The
base class is imported lazily inside __init__ so this module imports
cleanly even when pyautogen isn't installed — users opt in via
`pip install parry[autogen]`.

Usage:
    from parry.wrappers.autogen import ParryConversableAgent

    agent = ParryConversableAgent(
        name="assistant",
        agent_id="my-autogen-agent",
        llm_config={"model": "gpt-4o"},
    )

Fail-open: intercept errors are swallowed; the LLM reply is always
returned to the caller unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")


def _conversable_agent_base() -> type:
    try:
        from autogen import ConversableAgent  # type: ignore
    except ImportError as e:
        raise ImportError(
            "pyautogen not installed. Install with: pip install parry[autogen]"
        ) from e
    return ConversableAgent


def _last_user_message(messages: Any) -> str | None:
    if not messages:
        return None
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content:
                    return content
    return None


def _extract_reply_text(reply: Any) -> str | None:
    """generate_reply can return a string, dict, or tuple depending on
    AutoGen version and caller context. Pull text out of whatever we got."""
    if reply is None:
        return None
    if isinstance(reply, str):
        return reply
    if isinstance(reply, tuple) and reply:
        return _extract_reply_text(reply[-1])
    if isinstance(reply, dict):
        content = reply.get("content")
        if isinstance(content, str):
            return content
    return None


class _ParryAutogenMixin:
    """Instrumentation mixin applied on top of ConversableAgent."""

    def __init__(
        self,
        *args: Any,
        parry_agent_id: str | None = None,
        parry_session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self._parry_agent_id = parry_agent_id
        self._parry_session_id = parry_session_id

    def generate_reply(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        start = time.monotonic()
        messages = kwargs.get("messages")
        if messages is None and args:
            messages = args[0]
        prompt = _last_user_message(messages)

        reply = super().generate_reply(*args, **kwargs)  # type: ignore[misc]

        latency_ms = int((time.monotonic() - start) * 1000)
        response_text = _extract_reply_text(reply)
        model = None
        llm_config = getattr(self, "llm_config", None)
        if isinstance(llm_config, dict):
            model = llm_config.get("model")

        try:
            intercept_completion(
                prompt=prompt,
                response=response_text,
                model=model,
                tool_calls=None,
                token_count=None,
                latency_ms=latency_ms,
                agent_id=self._parry_agent_id,
                session_id=self._parry_session_id,
            )
        except Exception:
            logger.warning("parry.autogen.intercept_failed", exc_info=True)

        return reply


def ParryConversableAgent(  # noqa: N802
    *args: Any,
    agent_id: str | None = None,
    session_id: str | None = None,
    **kwargs: Any,
):
    """Factory returning a ConversableAgent subclass with Parry instrumentation.

    This is a function rather than a class because ConversableAgent
    must be imported lazily — if we defined `class ParryConversableAgent(ConversableAgent)`
    at module level it would fail to import without pyautogen installed.
    """
    base = _conversable_agent_base()

    class _ParryConversableAgent(_ParryAutogenMixin, base):  # type: ignore[misc, valid-type]
        pass

    return _ParryConversableAgent(
        *args,
        parry_agent_id=agent_id,
        parry_session_id=session_id,
        **kwargs,
    )
