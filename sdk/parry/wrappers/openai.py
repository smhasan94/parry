"""Drop-in OpenAI wrapper that intercepts completions for Parry."""

from __future__ import annotations

import logging
from typing import Any

from parry.interceptor import TimingContext, intercept_completion

logger = logging.getLogger("parry")


class ParryOpenAI:
    """Wraps openai.OpenAI to intercept chat completions transparently.

    Usage:
        from parry.wrappers.openai import ParryOpenAI
        client = ParryOpenAI()
        response = client.chat.completions.create(model="gpt-4o", messages=[...])
    """

    def __init__(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            import openai
        except ImportError:
            raise ImportError("Install openai: pip install parry[openai]")

        self._client = openai.OpenAI(**kwargs)
        self._agent_id = agent_id
        self._session_id = session_id
        self.chat = _ChatNamespace(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ChatNamespace:
    def __init__(self, wrapper: ParryOpenAI) -> None:
        self._wrapper = wrapper
        self.completions = _CompletionsNamespace(wrapper)


class _CompletionsNamespace:
    def __init__(self, wrapper: ParryOpenAI) -> None:
        self._wrapper = wrapper

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages", [])
        prompt = messages[-1].get("content", "") if messages else ""
        model = kwargs.get("model")

        with TimingContext() as timing:
            result = self._wrapper._client.chat.completions.create(**kwargs)

        # Extract response content
        response_text = None
        tool_calls_data = None
        token_count = None

        try:
            choice = result.choices[0]
            response_text = choice.message.content

            if choice.message.tool_calls:
                tool_calls_data = [
                    {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in choice.message.tool_calls
                ]

            if result.usage:
                token_count = result.usage.total_tokens
        except (IndexError, AttributeError):
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
