"""Tests for parry_instrument (Pydantic AI wrapper).

Uses plain Python stand-ins for pydantic_ai.Agent — no framework
import required. Covers the sync patch path, async patch path, and
the graceful no-op when the attribute path can't be resolved.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

import parry
from parry.wrappers.pydantic_ai import parry_instrument


class _FakeResult:
    def __init__(self, text: str, total_tokens: int = 15):
        self.content = text
        self.usage = MagicMock()
        self.usage.total_tokens = total_tokens


class _FakeModel:
    """Stand-in for pydantic_ai's internal Model wrapper."""

    model_name = "gpt-4o"

    def request(self, messages, **kwargs):
        return _FakeResult("Paris is the capital.")


class _FakeAgent:
    def __init__(self):
        self.model = _FakeModel()


class _FakeAsyncModel:
    model_name = "claude-sonnet-4-6"

    async def request(self, messages, **kwargs):
        await asyncio.sleep(0)
        return _FakeResult("hi", total_tokens=8)


class _FakeAsyncAgent:
    def __init__(self):
        self.model = _FakeAsyncModel()


def test_sync_instrumentation_calls_intercept():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    agent = _FakeAgent()

    with patch("parry.wrappers.pydantic_ai.intercept_completion") as mock_intercept:
        parry_instrument(agent, agent_id="my-pa", session_id="s")
        result = agent.model.request(
            messages=[{"role": "user", "content": "What is the capital of France?"}]
        )

    assert isinstance(result, _FakeResult)
    assert result.content == "Paris is the capital."
    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args.kwargs
    assert kw["prompt"] == "What is the capital of France?"
    assert kw["response"] == "Paris is the capital."
    assert kw["model"] == "gpt-4o"
    assert kw["token_count"] == 15
    assert kw["agent_id"] == "my-pa"


@pytest.mark.asyncio
async def test_async_instrumentation_calls_intercept():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    agent = _FakeAsyncAgent()

    with patch("parry.wrappers.pydantic_ai.intercept_completion") as mock_intercept:
        parry_instrument(agent, agent_id="my-pa-async")
        result = await agent.model.request(
            messages=[{"role": "user", "content": "hi"}]
        )

    assert result.content == "hi"
    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args.kwargs
    assert kw["prompt"] == "hi"
    assert kw["response"] == "hi"
    assert kw["model"] == "claude-sonnet-4-6"
    assert kw["token_count"] == 8


def test_instrument_noops_when_model_missing():
    """Agent without model/_model attr must be returned untouched — a
    log warning is fine, an exception is not."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    class _Empty:
        pass

    empty = _Empty()
    returned = parry_instrument(empty, agent_id="x")
    assert returned is empty
    # No attribute was added
    assert not hasattr(empty, "model")


def test_instrument_fail_open_on_intercept_error():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    agent = _FakeAgent()

    with patch(
        "parry.wrappers.pydantic_ai.intercept_completion",
        side_effect=RuntimeError("boom"),
    ):
        parry_instrument(agent, agent_id="x")
        # Real response must still return cleanly
        result = agent.model.request(messages=[{"role": "user", "content": "hi"}])

    assert isinstance(result, _FakeResult)
