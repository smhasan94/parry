"""Tests for ParryCrewAICallback.

The wrapper is pure Python and doesn't import crewai at module load
time, so these tests run without the extra installed. We invoke the
callback lifecycle directly with mock payloads and verify
intercept_completion sees the right fields.
"""

from unittest.mock import MagicMock, patch

import parry
from parry.wrappers.crewai import ParryCrewAICallback


def test_start_end_calls_intercept_with_correct_fields():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    cb = ParryCrewAICallback(agent_id="my-crew", session_id="sess-1")

    with patch("parry.wrappers.crewai.intercept_completion") as mock_intercept:
        cb.on_llm_start(
            serialized={"model": "gpt-4o"},
            prompts={"prompt": "What is 2+2?"},
            run_id="run-1",
            model="gpt-4o",
        )

        response_obj = MagicMock()
        response_obj.usage.total_tokens = 42
        cb.on_llm_end(
            response={"output": "4", "response": "4"},
            run_id="run-1",
            model="gpt-4o",
        )

    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args.kwargs
    assert kw["prompt"] == "What is 2+2?"
    assert kw["response"] == "4"
    assert kw["agent_id"] == "my-crew"
    assert kw["session_id"] == "sess-1"
    assert kw["latency_ms"] is not None


def test_fail_open_when_intercept_raises():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    cb = ParryCrewAICallback(agent_id="c")

    with patch(
        "parry.wrappers.crewai.intercept_completion",
        side_effect=RuntimeError("boom"),
    ):
        cb.on_llm_start(prompts={"prompt": "hi"}, run_id="r")
        # Must not raise
        cb.on_llm_end(response={"output": "ok"}, run_id="r")


def test_on_llm_error_drops_run_state_without_reporting():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    cb = ParryCrewAICallback(agent_id="c")

    with patch("parry.wrappers.crewai.intercept_completion") as mock_intercept:
        cb.on_llm_start(prompts={"prompt": "hi"}, run_id="r1")
        cb.on_llm_error(error=RuntimeError("LLM failed"), run_id="r1")

    mock_intercept.assert_not_called()
    assert "r1" not in cb._runs
