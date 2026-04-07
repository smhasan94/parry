"""Pydantic AI instrumentation for Parry.

Pydantic AI doesn't expose a public callback protocol like LangChain
or LlamaIndex; it's built around typed Agent/Model pairs. We
instrument by monkey-patching the agent's underlying model.request
method with a timing + intercept wrapper. This is intentionally
loose — pydantic_ai's internal API changes between 0.0.x releases
and we want the patch to no-op gracefully rather than crash when a
version rename breaks the attribute path.

Usage:
    from pydantic_ai import Agent
    from parry.wrappers.pydantic_ai import parry_instrument

    agent = Agent("openai:gpt-4o")
    parry_instrument(agent, agent_id="my-pydantic-agent")

Fail-open: any error inside the patched method (including patching
itself) lets the underlying request through unchanged.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")


def _extract_prompt_from_args(args: tuple, kwargs: dict) -> str | None:
    """Pydantic AI passes messages as positional or keyword arg. Pull the
    last user message content across a few shapes we've seen in the
    0.0.x line: list[ModelMessage], list[dict], or a raw string."""
    messages = kwargs.get("messages")
    if messages is None and args:
        for arg in args:
            if isinstance(arg, list | tuple):
                messages = arg
                break
            if isinstance(arg, str):
                return arg

    if isinstance(messages, str):
        return messages
    if isinstance(messages, list | tuple) and messages:
        last = messages[-1]
        # ModelMessage dataclass has a .parts attr with .content or .text
        parts = getattr(last, "parts", None)
        if parts:
            for part in parts:
                text = getattr(part, "content", None) or getattr(part, "text", None)
                if isinstance(text, str) and text:
                    return text
        # Plain dict message
        if isinstance(last, dict):
            content = last.get("content")
            if isinstance(content, str):
                return content
        # Direct string
        if isinstance(last, str):
            return last
    return None


def _extract_response(result: Any) -> tuple[str | None, int | None]:
    """Pull text + token count from a pydantic_ai response object."""
    if result is None:
        return None, None

    # Common shapes across versions
    text = (
        getattr(result, "content", None)
        or getattr(result, "text", None)
        or getattr(result, "output", None)
    )
    if not isinstance(text, str):
        text = None

    tokens = None
    usage = getattr(result, "usage", None)
    if usage is not None:
        tokens = (
            getattr(usage, "total_tokens", None)
            or getattr(usage, "response_tokens", None)
            or None
        )
    return text, tokens


def parry_instrument(
    agent: Any,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Patch a pydantic_ai.Agent in place to report every LLM call to Parry.

    Returns the same agent for chaining. The patch walks
    agent.model.request (or agent._model.request, depending on the
    version) and replaces it with a wrapper. If the attribute path
    doesn't resolve, we log and return the agent untouched — Parry
    stays silent rather than breaking the user's pipeline.
    """
    target = None
    owner = None
    for attr in ("model", "_model"):
        candidate = getattr(agent, attr, None)
        if candidate is not None and hasattr(candidate, "request"):
            target = candidate.request
            owner = candidate
            break

    if target is None or owner is None:
        logger.warning(
            "parry.pydantic_ai.instrument_skipped",
            extra={"reason": "could not locate agent.model.request"},
        )
        return agent

    is_coroutine = inspect.iscoroutinefunction(target)

    def _report(prompt: str | None, model_name: str | None, result: Any, latency_ms: int):
        response_text, tokens = _extract_response(result)
        try:
            intercept_completion(
                prompt=prompt,
                response=response_text,
                model=model_name,
                tool_calls=None,
                token_count=tokens,
                latency_ms=latency_ms,
                agent_id=agent_id,
                session_id=session_id,
            )
        except Exception:
            logger.warning("parry.pydantic_ai.intercept_failed", exc_info=True)

    if is_coroutine:
        async def _async_wrapper(*args: Any, **kwargs: Any):
            start = time.monotonic()
            prompt = _extract_prompt_from_args(args, kwargs)
            try:
                result = await target(*args, **kwargs)
            except Exception:
                raise
            latency_ms = int((time.monotonic() - start) * 1000)
            model_name = getattr(owner, "model_name", None) or getattr(owner, "name", None)
            _report(prompt, model_name, result, latency_ms)
            return result

        owner.request = _async_wrapper  # type: ignore[attr-defined]
    else:
        def _sync_wrapper(*args: Any, **kwargs: Any):
            start = time.monotonic()
            prompt = _extract_prompt_from_args(args, kwargs)
            result = target(*args, **kwargs)
            latency_ms = int((time.monotonic() - start) * 1000)
            model_name = getattr(owner, "model_name", None) or getattr(owner, "name", None)
            _report(prompt, model_name, result, latency_ms)
            return result

        owner.request = _sync_wrapper  # type: ignore[attr-defined]

    return agent
