"""Tests for the auto_instrument middleware."""

from unittest.mock import MagicMock, patch

from parry.middleware.auto_instrument import (
    _send_openai_event,
    _send_anthropic_event,
    auto_instrument,
    reset,
)


def test_auto_instrument_only_patches_once():
    """Calling auto_instrument twice should only patch once."""
    reset()
    with patch("parry.middleware.auto_instrument._patch_openai") as mock_oai, \
         patch("parry.middleware.auto_instrument._patch_anthropic") as mock_anth:
        auto_instrument()
        auto_instrument()  # second call should be no-op
        mock_oai.assert_called_once()
        mock_anth.assert_called_once()
    reset()


def test_auto_instrument_can_skip_openai():
    reset()
    with patch("parry.middleware.auto_instrument._patch_openai") as mock_oai, \
         patch("parry.middleware.auto_instrument._patch_anthropic") as mock_anth:
        auto_instrument(openai=False)
        mock_oai.assert_not_called()
        mock_anth.assert_called_once()
    reset()


def test_auto_instrument_can_skip_anthropic():
    reset()
    with patch("parry.middleware.auto_instrument._patch_openai") as mock_oai, \
         patch("parry.middleware.auto_instrument._patch_anthropic") as mock_anth:
        auto_instrument(anthropic=False)
        mock_oai.assert_called_once()
        mock_anth.assert_not_called()
    reset()


def test_send_openai_event_extracts_prompt():
    """Should extract the last user message as prompt."""
    kwargs = {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello world"},
        ],
        "model": "gpt-4o",
    }

    result = MagicMock()
    result.choices = [MagicMock()]
    result.choices[0].message.content = "Hi there!"
    result.choices[0].message.tool_calls = None
    result.usage.total_tokens = 50
    result.model = "gpt-4o"

    with patch("parry.middleware.auto_instrument.intercept_completion") as mock_ic:
        _send_openai_event(kwargs, result, 100, agent_id="test", session_id=None)
        mock_ic.assert_called_once()
        call_kwargs = mock_ic.call_args[1]
        assert call_kwargs["prompt"] == "Hello world"
        assert call_kwargs["response"] == "Hi there!"
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["token_count"] == 50
        assert call_kwargs["latency_ms"] == 100


def test_send_openai_event_extracts_tool_calls():
    kwargs = {"messages": [{"role": "user", "content": "Do something"}], "model": "gpt-4o"}

    tc = MagicMock()
    tc.function.name = "search"
    tc.function.arguments = '{"query": "test"}'

    result = MagicMock()
    result.choices = [MagicMock()]
    result.choices[0].message.content = None
    result.choices[0].message.tool_calls = [tc]
    result.usage.total_tokens = 30
    result.model = "gpt-4o"

    with patch("parry.middleware.auto_instrument.intercept_completion") as mock_ic:
        _send_openai_event(kwargs, result, 50, agent_id="test", session_id=None)
        call_kwargs = mock_ic.call_args[1]
        assert call_kwargs["tool_calls"] == [{"name": "search", "arguments": '{"query": "test"}'}]


def test_send_anthropic_event_extracts_prompt():
    kwargs = {
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "model": "claude-sonnet-4-6",
    }

    text_block = MagicMock()
    text_block.text = "Why did the chicken..."
    text_block.type = "text"

    result = MagicMock()
    result.content = [text_block]
    result.usage.input_tokens = 10
    result.usage.output_tokens = 20
    result.model = "claude-sonnet-4-6"

    with patch("parry.middleware.auto_instrument.intercept_completion") as mock_ic:
        _send_anthropic_event(kwargs, result, 200, agent_id="test", session_id=None)
        call_kwargs = mock_ic.call_args[1]
        assert call_kwargs["prompt"] == "Tell me a joke"
        assert call_kwargs["response"] == "Why did the chicken..."
        assert call_kwargs["token_count"] == 30
        assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_send_anthropic_event_extracts_tool_use():
    kwargs = {"messages": [{"role": "user", "content": "Search for it"}], "model": "claude-sonnet-4-6"}

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "web_search"
    tool_block.input = {"query": "test"}

    # No text attribute on tool blocks
    del tool_block.text

    result = MagicMock()
    result.content = [tool_block]
    result.usage.input_tokens = 15
    result.usage.output_tokens = 25
    result.model = "claude-sonnet-4-6"

    with patch("parry.middleware.auto_instrument.intercept_completion") as mock_ic:
        _send_anthropic_event(kwargs, result, 150, agent_id="test", session_id=None)
        call_kwargs = mock_ic.call_args[1]
        assert call_kwargs["tool_calls"] == [{"name": "web_search", "arguments": {"query": "test"}}]


def test_reset_allows_re_patching():
    reset()
    with patch("parry.middleware.auto_instrument._patch_openai") as mock_oai, \
         patch("parry.middleware.auto_instrument._patch_anthropic"):
        auto_instrument()
        assert mock_oai.call_count == 1
    reset()
    with patch("parry.middleware.auto_instrument._patch_openai") as mock_oai2, \
         patch("parry.middleware.auto_instrument._patch_anthropic"):
        auto_instrument()
        assert mock_oai2.call_count == 1
    reset()
