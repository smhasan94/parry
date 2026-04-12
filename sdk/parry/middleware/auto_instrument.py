"""Auto-instrument OpenAI and Anthropic clients globally.

Patches the `create` method on chat completions so every LLM call
goes through Parry's detection pipeline — regardless of which
framework (LangGraph, CrewAI, AutoGen, raw SDK) is making the call.

Usage:
    import parry
    parry.init(api_key="sk-parry-...", agent_id="my-agent")

    from parry.middleware.auto_instrument import auto_instrument
    auto_instrument()

    # Now ANY code using openai or anthropic is monitored:
    client = openai.OpenAI()
    client.chat.completions.create(...)  # automatically intercepted
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")

_patched = False


def auto_instrument(
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
    openai: bool = True,
    anthropic: bool = True,
) -> None:
    """Monkey-patch LLM SDKs to route all calls through Parry.

    Safe to call multiple times — only patches once.

    Args:
        agent_id: Override agent_id (falls back to parry.init default).
        session_id: Optional session_id attached to all events.
        openai: Patch openai.ChatCompletion.create if True.
        anthropic: Patch anthropic.Messages.create if True.
    """
    global _patched
    if _patched:
        return
    _patched = True

    if openai:
        _patch_openai(agent_id=agent_id, session_id=session_id)
    if anthropic:
        _patch_anthropic(agent_id=agent_id, session_id=session_id)

    logger.info("parry.auto_instrument: LLM clients patched")


def _patch_openai(*, agent_id: str | None, session_id: str | None) -> None:
    """Patch openai.resources.chat.completions.Completions.create."""
    try:
        from openai.resources.chat import completions as oai_mod

        original = oai_mod.Completions.create

        @functools.wraps(original)
        def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            result = original(self, *args, **kwargs)
            latency_ms = int((time.monotonic() - start) * 1000)

            try:
                _send_openai_event(
                    kwargs, result, latency_ms,
                    agent_id=agent_id, session_id=session_id,
                )
            except Exception:
                logger.debug("parry.auto_instrument.openai: intercept failed", exc_info=True)

            return result

        oai_mod.Completions.create = patched_create  # type: ignore[assignment]
        logger.debug("parry.auto_instrument: patched openai.Completions.create")
    except ImportError:
        logger.debug("parry.auto_instrument: openai not installed, skipping")
    except Exception:
        logger.debug("parry.auto_instrument: failed to patch openai", exc_info=True)


def _patch_anthropic(*, agent_id: str | None, session_id: str | None) -> None:
    """Patch anthropic.resources.messages.Messages.create."""
    try:
        from anthropic.resources import messages as anth_mod

        original = anth_mod.Messages.create

        @functools.wraps(original)
        def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            result = original(self, *args, **kwargs)
            latency_ms = int((time.monotonic() - start) * 1000)

            try:
                _send_anthropic_event(
                    kwargs, result, latency_ms,
                    agent_id=agent_id, session_id=session_id,
                )
            except Exception:
                logger.debug("parry.auto_instrument.anthropic: intercept failed", exc_info=True)

            return result

        anth_mod.Messages.create = patched_create  # type: ignore[assignment]
        logger.debug("parry.auto_instrument: patched anthropic.Messages.create")
    except ImportError:
        logger.debug("parry.auto_instrument: anthropic not installed, skipping")
    except Exception:
        logger.debug("parry.auto_instrument: failed to patch anthropic", exc_info=True)


def _send_openai_event(
    kwargs: dict[str, Any],
    result: Any,
    latency_ms: int,
    *,
    agent_id: str | None,
    session_id: str | None,
) -> None:
    """Extract event data from an OpenAI chat completion."""
    messages = kwargs.get("messages", [])
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            prompt = content if isinstance(content, str) else str(content)
            break

    response_text = None
    tool_calls_data = None
    token_count = None
    model = kwargs.get("model")

    if hasattr(result, "choices") and result.choices:
        choice = result.choices[0]
        if hasattr(choice, "message"):
            msg = choice.message
            response_text = getattr(msg, "content", None)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls_data = [
                    {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in msg.tool_calls
                ]

    if hasattr(result, "usage") and result.usage:
        token_count = getattr(result.usage, "total_tokens", None)

    if hasattr(result, "model"):
        model = result.model

    intercept_completion(
        prompt=prompt,
        response=response_text,
        model=model,
        tool_calls=tool_calls_data,
        token_count=token_count,
        latency_ms=latency_ms,
        agent_id=agent_id,
        session_id=session_id,
    )


def _send_anthropic_event(
    kwargs: dict[str, Any],
    result: Any,
    latency_ms: int,
    *,
    agent_id: str | None,
    session_id: str | None,
) -> None:
    """Extract event data from an Anthropic message response."""
    messages = kwargs.get("messages", [])
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                prompt = content
            elif isinstance(content, list):
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                prompt = " ".join(texts)
            break

    response_text = None
    tool_calls_data = None
    token_count = None
    model = kwargs.get("model")

    if hasattr(result, "content") and result.content:
        text_blocks = [b.text for b in result.content if hasattr(b, "text")]
        if text_blocks:
            response_text = " ".join(text_blocks)

        tool_blocks = [b for b in result.content if getattr(b, "type", None) == "tool_use"]
        if tool_blocks:
            tool_calls_data = [
                {"name": b.name, "arguments": b.input}
                for b in tool_blocks
            ]

    if hasattr(result, "usage"):
        usage = result.usage
        input_t = getattr(usage, "input_tokens", 0) or 0
        output_t = getattr(usage, "output_tokens", 0) or 0
        token_count = input_t + output_t

    if hasattr(result, "model"):
        model = result.model

    intercept_completion(
        prompt=prompt,
        response=response_text,
        model=model,
        tool_calls=tool_calls_data,
        token_count=token_count,
        latency_ms=latency_ms,
        agent_id=agent_id,
        session_id=session_id,
    )


def reset() -> None:
    """Reset instrumentation state (for testing)."""
    global _patched
    _patched = False
