"""Drop-in OpenAI wrapper that intercepts completions for Parry."""

from __future__ import annotations

import logging
from typing import Any

from parry.blocking import ParryBlockedError, check_before_call
from parry.interceptor import TimingContext, intercept_completion
from parry.response_scanner import scan_response_before_return

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
        except ImportError as e:
            raise ImportError("Install openai: pip install parry[openai]") from e

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

        # Blocking mode pre-flight. Raises ParryBlockedError if the proxy
        # rejects the call — we let that propagate so the host agent can
        # catch it. Any other failure is swallowed (fail open).
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

        # Streaming: collect chunks, intercept after completion, return generator
        if kwargs.get("stream"):
            return self._create_streaming(prompt, model, kwargs)

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

        # Post-LLM response scan. May raise ParryBlockedError (propagates
        # to the host agent) or return a redacted string we substitute
        # into the result before handing it back.
        if parry_client is not None and response_text is not None:
            cleaned = scan_response_before_return(
                parry_client,
                response_text,
                agent_id=self._wrapper._agent_id,
                session_id=self._wrapper._session_id,
            )
            if cleaned != response_text:
                try:
                    result.choices[0].message.content = cleaned
                except (IndexError, AttributeError):
                    logger.warning("parry: could not apply redaction to response object")

        return result

    def _create_streaming(self, prompt: str, model: str | None, kwargs: dict[str, Any]) -> Any:
        """Wrap streaming response: yield chunks to caller, intercept on completion."""
        chunks: list[str] = []
        timing = TimingContext()
        timing.__enter__()

        stream = self._wrapper._client.chat.completions.create(**kwargs)

        def _intercept_stream() -> Any:
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        chunks.append(delta.content)
                except (IndexError, AttributeError):
                    pass
                yield chunk

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
