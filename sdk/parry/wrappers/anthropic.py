"""Drop-in Anthropic wrapper that intercepts completions for Parry."""

from __future__ import annotations

import logging
from typing import Any

from parry.blocking import check_before_call
from parry.interceptor import TimingContext, intercept_completion
from parry.response_scanner import scan_response_before_return

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

        # Blocking mode pre-flight — see ParryOpenAI for the full contract.
        try:
            import parry

            parry_client = parry.get_client()
        except RuntimeError:
            parry_client = None
        if parry_client is not None:
            check_before_call(
                parry_client,
                prompt=prompt,
                model=model,
                agent_id=self._wrapper._agent_id,
                session_id=self._wrapper._session_id,
            )

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

        # Async ingest always sees the ORIGINAL (pre-scan) response so
        # the incident record in the dashboard has full forensic evidence.
        try:
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
        except Exception:
            logger.warning("parry.intercept_failed", exc_info=True)

        # Post-LLM response scan — see ParryOpenAI for the full contract.
        # Anthropic content is a list of blocks; we redact the first text
        # block in place and zero out subsequent text blocks so the
        # redacted content is what the host agent actually sees.
        if parry_client is not None and response_text is not None:
            cleaned = scan_response_before_return(
                parry_client,
                response_text,
                agent_id=self._wrapper._agent_id,
                session_id=self._wrapper._session_id,
            )
            if cleaned != response_text:
                try:
                    text_indexes = [
                        i
                        for i, b in enumerate(result.content)
                        if getattr(b, "type", None) == "text"
                    ]
                    if text_indexes:
                        result.content[text_indexes[0]].text = cleaned
                        for i in text_indexes[1:]:
                            result.content[i].text = ""
                except (AttributeError, TypeError):
                    logger.warning("parry: could not apply redaction to response object")

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

            try:
                intercept_completion(
                    prompt=prompt,
                    response="".join(chunks) if chunks else None,
                    model=model,
                    latency_ms=timing.latency_ms,
                    agent_id=self._wrapper._agent_id,
                    session_id=self._wrapper._session_id,
                )
            except Exception:
                logger.warning("parry.intercept_failed", exc_info=True)

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
