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
        except ImportError as e:
            raise ImportError("Install anthropic: pip install parry[anthropic]") from e

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
        prompt = _extract_prompt(messages)
        model = kwargs.get("model")

        # Streaming: collect chunks, intercept after completion
        if kwargs.get("stream"):
            return self._create_streaming(prompt, model, kwargs)

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
                tool_calls_data = [{"name": b.name, "arguments": b.input} for b in tool_blocks]

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

    def _create_streaming(self, prompt: str, model: str | None, kwargs: dict[str, Any]) -> Any:
        """Wrap streaming response: yield events to caller, intercept on completion."""
        chunks: list[str] = []
        timing = TimingContext()
        timing.__enter__()

        stream = self._wrapper._client.messages.create(**kwargs)

        def _intercept_stream() -> Any:
            for event in stream:
                try:
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        chunks.append(event.delta.text)
                except AttributeError:
                    pass
                yield event

            timing.__exit__(None, None, None)

            intercept_completion(
                prompt=prompt,
                response="".join(chunks) if chunks else None,
                model=model,
                latency_ms=timing.latency_ms,
                agent_id=self._wrapper._agent_id,
                session_id=self._wrapper._session_id,
            )

        return _intercept_stream()


def _extract_prompt(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    last = messages[-1]
    if isinstance(last.get("content"), str):
        return last["content"]
    if isinstance(last.get("content"), list):
        text_parts = [b["text"] for b in last["content"] if b.get("type") == "text"]
        return " ".join(text_parts)
    return ""
