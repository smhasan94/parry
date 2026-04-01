"""Drop-in Anthropic wrapper that intercepts completions for Parry."""

from __future__ import annotations

import logging
from typing import Any

from parry.interceptor import TimingContext, intercept_completion

logger = logging.getLogger("parry")


class ParryAnthropic:
    """Wraps anthropic.Anthropic to intercept message completions transparently.

    Usage:
        from parry.wrappers.anthropic import ParryAnthropic
        client = ParryAnthropic()
        response = client.messages.create(model="claude-sonnet-4-6", messages=[...])
    """

    def __init__(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install parry[anthropic]")

        self._client = anthropic.Anthropic(**kwargs)
        self._agent_id = agent_id
        self._session_id = session_id
        self.messages = _MessagesNamespace(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _MessagesNamespace:
    def __init__(self, wrapper: ParryAnthropic) -> None:
        self._wrapper = wrapper

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages", [])
        prompt = ""
        if messages:
            last = messages[-1]
            if isinstance(last.get("content"), str):
                prompt = last["content"]
            elif isinstance(last.get("content"), list):
                text_parts = [b["text"] for b in last["content"] if b.get("type") == "text"]
                prompt = " ".join(text_parts)

        model = kwargs.get("model")

        with TimingContext() as timing:
            result = self._wrapper._client.messages.create(**kwargs)

        # Extract response
        response_text = None
        tool_calls_data = None
        token_count = None

        try:
            text_blocks = [b.text for b in result.content if b.type == "text"]
            response_text = " ".join(text_blocks) if text_blocks else None

            tool_blocks = [b for b in result.content if b.type == "tool_use"]
            if tool_blocks:
                tool_calls_data = [
                    {"name": b.name, "arguments": b.input}
                    for b in tool_blocks
                ]

            if result.usage:
                token_count = result.usage.input_tokens + result.usage.output_tokens
        except AttributeError:
            pass

        intercept_completion(
            prompt=prompt,
            response=response_text,
            model=model,
            tool_calls=tool_calls_data,
            token_count=token_count,
            latency_ms=timing.latency_ms,
            agent_id=self._wrapper._agent_id,
            session_id=self._wrapper._session_id,
        )

        return result
