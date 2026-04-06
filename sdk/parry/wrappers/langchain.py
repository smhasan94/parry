"""LangChain callback handler that intercepts LLM calls for Parry.

Usage:
    from parry.wrappers.langchain import ParryCallbackHandler

    handler = ParryCallbackHandler(agent_id="my-agent")
    chain.invoke("What is 2+2?", config={"callbacks": [handler]})
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from parry.interceptor import intercept_completion

logger = logging.getLogger("parry")

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult
except ImportError as e:
    raise ImportError("Install langchain-core: pip install parry[langchain]") from e


class ParryCallbackHandler(BaseCallbackHandler):
    """LangChain callback that sends LLM call data to Parry.

    Tracks prompt, response, model, tool calls, token usage, and latency
    for every LLM invocation in a chain or agent.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.session_id = session_id

        # Per-run state keyed by run_id
        self._runs: dict[UUID, dict[str, Any]] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Capture prompt and model when a chat model starts."""
        # Extract the last user message as prompt
        prompt = ""
        if messages and messages[0]:
            last_msg = messages[0][-1]
            if isinstance(last_msg.content, str):
                prompt = last_msg.content
            elif isinstance(last_msg.content, list):
                text_parts = [
                    b["text"]
                    for b in last_msg.content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                prompt = " ".join(text_parts)

        # Extract model name from serialized kwargs or metadata
        model = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("id", [""])[-1]
        )

        self._runs[run_id] = {
            "prompt": prompt,
            "model": model or None,
            "start_time": time.monotonic(),
            "tool_calls": [],
        }

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Fallback for non-chat models (plain LLMs)."""
        prompt = prompts[0] if prompts else ""
        model = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("id", [""])[-1]
        )

        self._runs[run_id] = {
            "prompt": prompt,
            "model": model or None,
            "start_time": time.monotonic(),
            "tool_calls": [],
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send the completed LLM call to Parry."""
        run = self._runs.pop(run_id, None)
        if run is None:
            return

        latency_ms = int((time.monotonic() - run["start_time"]) * 1000)

        # Extract response text
        response_text = None
        if response.generations and response.generations[0]:
            response_text = response.generations[0][0].text

        # Extract token usage from llm_output
        token_count = None
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})
            token_count = usage.get("total_tokens")

        # Extract tool calls from AIMessage if present
        tool_calls_data = None
        gen = (
            response.generations[0][0] if response.generations and response.generations[0] else None
        )
        if gen and hasattr(gen, "message"):
            msg = gen.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls_data = [
                    {"name": tc.get("name", ""), "arguments": tc.get("args", {})}
                    for tc in msg.tool_calls
                ]

        # Merge any tool calls collected during the run
        if run["tool_calls"] and not tool_calls_data:
            tool_calls_data = run["tool_calls"]

        intercept_completion(
            prompt=run["prompt"],
            response=response_text,
            model=run["model"],
            tool_calls=tool_calls_data if tool_calls_data else None,
            token_count=token_count,
            latency_ms=latency_ms,
            agent_id=self.agent_id,
            session_id=self.session_id,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Clean up run state on error."""
        self._runs.pop(run_id, None)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Track tool calls made during an LLM run."""
        if parent_run_id and parent_run_id in self._runs:
            tool_name = serialized.get("name") or serialized.get("id", ["tool"])[-1]
            self._runs[parent_run_id]["tool_calls"].append(
                {"name": tool_name, "arguments": inputs or input_str}
            )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """No-op — tool output captured by the LLM's response."""
        pass
