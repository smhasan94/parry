"""CrewAI callback wrapper for Parry.

CrewAI's LLM callback protocol is a loose duck-typed interface: the
framework calls `on_llm_start` and `on_llm_end` on anything in its
`callbacks` list. We don't subclass crewai's BaseCallback directly
because the class moved between minor versions — duck-typing is
more resilient across supported crewai releases.

Usage:
    from parry.wrappers.crewai import ParryCrewAICallback

    crew = Crew(
        agents=[...],
        tasks=[...],
        callbacks=[ParryCrewAICallback(agent_id="my-crew")],
    )

Fail-open contract matches the OpenAI/Anthropic wrappers: any
exception inside intercept_completion is swallowed so the crew run
cannot be broken by a Parry-side error.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")


def _extract_prompt(payload: Any) -> str | None:
    """CrewAI passes different shapes across versions. Best-effort pull."""
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        # Common keys seen across crewai versions
        for key in ("prompt", "input", "messages"):
            val = payload.get(key)
            if isinstance(val, str):
                return val
            if isinstance(val, list) and val:
                last = val[-1]
                if isinstance(last, dict) and isinstance(last.get("content"), str):
                    return last["content"]
                if isinstance(last, str):
                    return last
    return None


def _extract_response(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("output", "response", "content", "text"):
            val = payload.get(key)
            if isinstance(val, str):
                return val
    # Some crewai versions pass a LLMResult-like object with .generations
    generations = getattr(payload, "generations", None)
    if generations:
        try:
            return generations[0][0].text
        except (IndexError, AttributeError):
            pass
    text_attr = getattr(payload, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    return None


class ParryCrewAICallback:
    """Duck-typed CrewAI LLM callback that reports every LLM call to Parry."""

    def __init__(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        # run_id → (start_monotonic, prompt). CrewAI invokes callbacks from
        # the same thread so a plain dict is safe.
        self._runs: dict[str, tuple[float, str | None]] = {}

    # ── CrewAI callback surface ──────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Any = None,
        prompts: Any = None,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        key = str(run_id) if run_id is not None else "_default"
        prompt = _extract_prompt(prompts) or _extract_prompt(kwargs)
        self._runs[key] = (time.monotonic(), prompt)

    def on_llm_end(
        self,
        response: Any = None,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        key = str(run_id) if run_id is not None else "_default"
        start, prompt = self._runs.pop(key, (time.monotonic(), None))
        latency_ms = int((time.monotonic() - start) * 1000)

        response_text = _extract_response(response)
        model = None
        token_count = None
        if isinstance(kwargs, dict):
            model = kwargs.get("model") or kwargs.get("model_name")
        # CrewAI sometimes attaches usage info on the response object
        usage = getattr(response, "usage", None)
        if usage is not None:
            token_count = (
                getattr(usage, "total_tokens", None)
                or getattr(usage, "output_tokens", None)
                or None
            )

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
            logger.warning("parry.crewai.intercept_failed", exc_info=True)

    def on_llm_error(self, error: Any = None, *, run_id: Any = None, **kwargs: Any) -> None:
        """Drop the run state without emitting an event — the LLM call
        itself errored so there's no response to report."""
        key = str(run_id) if run_id is not None else "_default"
        self._runs.pop(key, None)
