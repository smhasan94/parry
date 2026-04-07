"""Tests for the LlamaIndex ParryCallbackHandler factory.

Monkey-patches the lazy base-class and event-type lookups so the
tests run without llama-index-core installed.
"""
from unittest.mock import MagicMock, patch

import parry
from parry.wrappers import llamaindex as llamaindex_mod


class _StubBaseHandler:
    def __init__(self, event_starts_to_ignore=None, event_ends_to_ignore=None):
        self.event_starts_to_ignore = event_starts_to_ignore or []
        self.event_ends_to_ignore = event_ends_to_ignore or []


class _FakeLLMEvent:
    """Sentinel matching CBEventType.LLM — equality works because it's
    the same object on both ends."""


_LLM_EVENT = _FakeLLMEvent()


def test_llm_event_lifecycle_reports_to_intercept():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    with (
        patch.object(llamaindex_mod, "_base_handler_class", return_value=_StubBaseHandler),
        patch.object(llamaindex_mod, "_llm_event_type", return_value=_LLM_EVENT),
        patch("parry.wrappers.llamaindex.intercept_completion") as mock_intercept,
    ):
        handler = llamaindex_mod.ParryCallbackHandler(agent_id="my-li", session_id="s")

        handler.on_event_start(
            _LLM_EVENT,
            payload={"prompt": "What is 2+2?"},
            event_id="ev1",
        )

        # Build a fake ChatResponse-ish object
        msg = MagicMock()
        msg.content = "4"
        response = MagicMock()
        response.message = msg
        response.text = "4"
        response.model = "gpt-4o"

        handler.on_event_end(
            _LLM_EVENT,
            payload={"response": response},
            event_id="ev1",
        )

    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args.kwargs
    assert kw["prompt"] == "What is 2+2?"
    assert kw["response"] == "4"
    assert kw["agent_id"] == "my-li"
    assert kw["session_id"] == "s"


def test_non_llm_events_are_ignored():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    with (
        patch.object(llamaindex_mod, "_base_handler_class", return_value=_StubBaseHandler),
        patch.object(llamaindex_mod, "_llm_event_type", return_value=_LLM_EVENT),
        patch("parry.wrappers.llamaindex.intercept_completion") as mock_intercept,
    ):
        handler = llamaindex_mod.ParryCallbackHandler(agent_id="c")

        class _OtherEvent:
            pass

        other = _OtherEvent()
        handler.on_event_start(other, payload={"prompt": "?"}, event_id="e1")
        handler.on_event_end(other, payload={"response": "hi"}, event_id="e1")

    mock_intercept.assert_not_called()


def test_fail_open_when_intercept_raises():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    with (
        patch.object(llamaindex_mod, "_base_handler_class", return_value=_StubBaseHandler),
        patch.object(llamaindex_mod, "_llm_event_type", return_value=_LLM_EVENT),
        patch(
            "parry.wrappers.llamaindex.intercept_completion",
            side_effect=RuntimeError("boom"),
        ),
    ):
        handler = llamaindex_mod.ParryCallbackHandler(agent_id="c")
        handler.on_event_start(_LLM_EVENT, payload={"prompt": "hi"}, event_id="e")
        # Must not raise
        handler.on_event_end(_LLM_EVENT, payload={"response": "ok"}, event_id="e")
