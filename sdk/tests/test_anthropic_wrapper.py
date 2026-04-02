"""Tests for ParryAnthropic wrapper — sync and streaming completions."""
from unittest.mock import MagicMock, patch

import parry
from parry.wrappers.anthropic import ParryAnthropic, _extract_prompt


def _make_text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name: str, input_data: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    return block


def _make_mock_response(
    content_blocks=None,
    input_tokens: int = 10,
    output_tokens: int = 20,
):
    """Build a mock Anthropic Message response."""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    resp = MagicMock()
    resp.content = content_blocks or [_make_text_block("Hello!")]
    resp.usage = usage
    return resp


def _make_streaming_events(texts: list[str]):
    """Build a list of mock streaming events with delta.text."""
    events = []
    for text in texts:
        evt = MagicMock()
        evt.delta = MagicMock()
        evt.delta.text = text
        events.append(evt)
    return events


# --- _extract_prompt tests ---


def test_extract_prompt_string_content():
    msgs = [{"role": "user", "content": "Hello"}]
    assert _extract_prompt(msgs) == "Hello"


def test_extract_prompt_block_content():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "Part 1"}, {"type": "text", "text": "Part 2"}]}]
    assert _extract_prompt(msgs) == "Part 1 Part 2"


def test_extract_prompt_empty():
    assert _extract_prompt([]) == ""


def test_extract_prompt_no_text_blocks():
    msgs = [{"role": "user", "content": [{"type": "image", "source": {}}]}]
    assert _extract_prompt(msgs) == ""


# --- Sync completion tests ---


@patch("parry.wrappers.anthropic.intercept_completion")
@patch("anthropic.Anthropic")
def test_sync_completion_intercepts(MockAnthropic, mock_intercept):
    """Sync completion extracts text blocks, tokens, and calls intercept."""
    mock_client = MockAnthropic.return_value
    mock_client.messages.create.return_value = _make_mock_response(
        content_blocks=[_make_text_block("Paris is the capital.")],
        input_tokens=15,
        output_tokens=10,
    )

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryAnthropic(agent_id="test-agent", api_key="fake")

    result = wrapper.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
        max_tokens=100,
    )

    # Original response returned unchanged
    assert result.content[0].text == "Paris is the capital."

    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args[1]
    assert kw["prompt"] == "What is the capital of France?"
    assert kw["response"] == "Paris is the capital."
    assert kw["model"] == "claude-sonnet-4-6"
    assert kw["token_count"] == 25  # 15 + 10
    assert kw["agent_id"] == "test-agent"


@patch("parry.wrappers.anthropic.intercept_completion")
@patch("anthropic.Anthropic")
def test_sync_completion_extracts_tool_use(MockAnthropic, mock_intercept):
    """Tool use blocks are extracted and passed to intercept."""
    mock_client = MockAnthropic.return_value
    mock_client.messages.create.return_value = _make_mock_response(
        content_blocks=[
            _make_text_block("I'll search for that."),
            _make_tool_use_block("search", {"query": "weather"}),
        ]
    )

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryAnthropic(agent_id="test-agent", api_key="fake")

    wrapper.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "Search weather"}],
        max_tokens=100,
    )

    kw = mock_intercept.call_args[1]
    assert kw["tool_calls"] is not None
    assert len(kw["tool_calls"]) == 1
    assert kw["tool_calls"][0]["name"] == "search"
    assert kw["tool_calls"][0]["arguments"] == {"query": "weather"}
    assert kw["response"] == "I'll search for that."


# --- Streaming tests ---


@patch("parry.wrappers.anthropic.intercept_completion")
@patch("anthropic.Anthropic")
def test_streaming_yields_all_events(MockAnthropic, mock_intercept):
    """Streaming yields events to caller and intercepts after stream ends."""
    events = _make_streaming_events(["Hello", " world", "!"])
    mock_client = MockAnthropic.return_value
    mock_client.messages.create.return_value = iter(events)

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryAnthropic(agent_id="test-agent", api_key="fake")

    result = wrapper.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "Say hello"}],
        max_tokens=100,
        stream=True,
    )

    received = list(result)
    assert len(received) == 3

    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args[1]
    assert kw["response"] == "Hello world!"
    assert kw["model"] == "claude-sonnet-4-6"


@patch("parry.wrappers.anthropic.intercept_completion")
@patch("anthropic.Anthropic")
def test_streaming_non_delta_events(MockAnthropic, mock_intercept):
    """Events without delta.text are yielded but don't contribute to response."""
    evt_no_delta = MagicMock(spec=[])  # no delta attribute
    evt_with_text = MagicMock()
    evt_with_text.delta = MagicMock()
    evt_with_text.delta.text = "content"

    mock_client = MockAnthropic.return_value
    mock_client.messages.create.return_value = iter([evt_no_delta, evt_with_text])

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryAnthropic(agent_id="test-agent", api_key="fake")

    result = wrapper.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "test"}],
        max_tokens=100,
        stream=True,
    )

    received = list(result)
    assert len(received) == 2  # both events yielded

    kw = mock_intercept.call_args[1]
    assert kw["response"] == "content"  # only the text delta


# --- Passthrough test ---


@patch("parry.wrappers.anthropic.intercept_completion")
@patch("anthropic.Anthropic")
def test_passthrough_attributes(MockAnthropic, mock_intercept):
    """Non-messages attributes pass through to underlying Anthropic client."""
    mock_client = MockAnthropic.return_value
    mock_client.count_tokens.return_value = 42

    wrapper = ParryAnthropic(api_key="fake")
    assert wrapper.count_tokens("hello") == 42
