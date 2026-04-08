"""Tests for the AutoGen ParryConversableAgent wrapper.

pyautogen isn't a hard dep so we don't require it here. Instead we
monkey-patch `_conversable_agent_base` to return a stub base class
that behaves like ConversableAgent's generate_reply surface, then
exercise the mixin via the factory.
"""

from unittest.mock import patch

import parry
from parry.wrappers import autogen as autogen_mod


class _StubBase:
    """Stand-in for autogen.ConversableAgent with just enough surface
    for the mixin's super() calls."""

    def __init__(self, *args, name: str = "", llm_config=None, **kwargs):
        self.name = name
        self.llm_config = llm_config or {}

    def generate_reply(self, messages=None, sender=None, **kwargs):
        return "4"


def test_factory_instruments_generate_reply():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    with (
        patch.object(autogen_mod, "_conversable_agent_base", return_value=_StubBase),
        patch("parry.wrappers.autogen.intercept_completion") as mock_intercept,
    ):
        agent = autogen_mod.ParryConversableAgent(
            name="assistant",
            agent_id="my-ag",
            session_id="s",
            llm_config={"model": "gpt-4o"},
        )

        result = agent.generate_reply(
            messages=[
                {"role": "user", "content": "What is 2+2?"},
            ]
        )

    assert result == "4"
    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args.kwargs
    assert kw["prompt"] == "What is 2+2?"
    assert kw["response"] == "4"
    assert kw["model"] == "gpt-4o"
    assert kw["agent_id"] == "my-ag"
    assert kw["session_id"] == "s"


def test_factory_fail_open_on_intercept_error():
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")

    with (
        patch.object(autogen_mod, "_conversable_agent_base", return_value=_StubBase),
        patch(
            "parry.wrappers.autogen.intercept_completion",
            side_effect=RuntimeError("boom"),
        ),
    ):
        agent = autogen_mod.ParryConversableAgent(
            name="a", agent_id="x", llm_config={"model": "gpt-4o"}
        )
        # The underlying generate_reply return must still surface cleanly
        result = agent.generate_reply(messages=[{"role": "user", "content": "hi"}])

    assert result == "4"


def test_missing_autogen_raises_helpful_error():
    """If autogen isn't installed, the factory should surface a clear
    ImportError pointing users at the right extra."""
    with patch.object(
        autogen_mod,
        "_conversable_agent_base",
        side_effect=ImportError(
            "pyautogen not installed. Install with: pip install parry[autogen]"
        ),
    ):
        import pytest

        with pytest.raises(ImportError) as exc:
            autogen_mod.ParryConversableAgent(name="a")
        assert "parry[autogen]" in str(exc.value)
