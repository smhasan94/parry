"""Tests for ParryOpenAI wrapper — sync and streaming completions."""
from unittest.mock import MagicMock, patch

import parry
from parry.wrappers.openai import ParryOpenAI


def _make_mock_response(
    content: str = "Hello!",
    tool_calls: list | None = None,
    total_tokens: int = 42,
):
    """Build a mock OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.total_tokens = total_tokens

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_mock_tool_call(name: str, arguments: str):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _make_streaming_chunks(texts: list[str]):
    """Build a list of mock streaming chunks."""
    chunks = []
    for text in texts:
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)
    return chunks


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_sync_completion_intercepts(MockOpenAI, mock_intercept):
    """Sync completion extracts response, model, tokens and calls intercept."""
    mock_client = MockOpenAI.return_value
    mock_client.chat.completions.create.return_value = _make_mock_response(
        content="Paris is the capital.", total_tokens=25
    )

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="test-agent", api_key="fake")

    result = wrapper.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
    )

    # Original response returned unchanged
    assert result.choices[0].message.content == "Paris is the capital."

    # intercept_completion called with extracted data
    mock_intercept.assert_called_once()
    call_kwargs = mock_intercept.call_args[1]
    assert call_kwargs["prompt"] == "What is the capital of France?"
    assert call_kwargs["response"] == "Paris is the capital."
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["token_count"] == 25
    assert call_kwargs["agent_id"] == "test-agent"
    assert call_kwargs["latency_ms"] is not None


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_sync_completion_extracts_tool_calls(MockOpenAI, mock_intercept):
    """Tool calls in the response are extracted and passed to intercept."""
    tool_calls = [
        _make_mock_tool_call("search", '{"query": "weather"}'),
        _make_mock_tool_call("read_file", '{"path": "/tmp/data.txt"}'),
    ]
    mock_client = MockOpenAI.return_value
    mock_client.chat.completions.create.return_value = _make_mock_response(
        content=None, tool_calls=tool_calls
    )

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="test-agent", api_key="fake")

    wrapper.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Check the weather"}],
    )

    call_kwargs = mock_intercept.call_args[1]
    assert call_kwargs["tool_calls"] is not None
    assert len(call_kwargs["tool_calls"]) == 2
    assert call_kwargs["tool_calls"][0]["name"] == "search"
    assert call_kwargs["tool_calls"][1]["name"] == "read_file"


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_sync_completion_empty_messages(MockOpenAI, mock_intercept):
    """Empty messages list doesn't crash — prompt defaults to empty string."""
    mock_client = MockOpenAI.return_value
    mock_client.chat.completions.create.return_value = _make_mock_response()

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="test-agent", api_key="fake")

    wrapper.chat.completions.create(model="gpt-4o", messages=[])

    call_kwargs = mock_intercept.call_args[1]
    assert call_kwargs["prompt"] == ""


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_streaming_yields_all_chunks(MockOpenAI, mock_intercept):
    """Streaming returns all chunks to the caller and intercepts after stream ends."""
    chunks = _make_streaming_chunks(["Hello", " world", "!"])
    mock_client = MockOpenAI.return_value
    mock_client.chat.completions.create.return_value = iter(chunks)

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="test-agent", api_key="fake")

    result = wrapper.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Say hello"}],
        stream=True,
    )

    # Consumer gets all chunks
    received = list(result)
    assert len(received) == 3

    # intercept called after stream consumed
    mock_intercept.assert_called_once()
    call_kwargs = mock_intercept.call_args[1]
    assert call_kwargs["response"] == "Hello world!"
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["agent_id"] == "test-agent"


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_streaming_empty_chunks(MockOpenAI, mock_intercept):
    """Streaming with no content in chunks yields None response."""
    empty_delta = MagicMock()
    empty_delta.content = None
    empty_choice = MagicMock()
    empty_choice.delta = empty_delta
    empty_chunk = MagicMock()
    empty_chunk.choices = [empty_choice]

    mock_client = MockOpenAI.return_value
    mock_client.chat.completions.create.return_value = iter([empty_chunk])

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="test-agent", api_key="fake")

    result = wrapper.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    list(result)

    call_kwargs = mock_intercept.call_args[1]
    assert call_kwargs["response"] is None


@patch("parry.wrappers.openai.intercept_completion")
@patch("openai.OpenAI")
def test_passthrough_attributes(MockOpenAI, mock_intercept):
    """Non-chat attributes pass through to underlying OpenAI client."""
    mock_client = MockOpenAI.return_value
    mock_client.models = MagicMock()
    mock_client.models.list.return_value = ["gpt-4o"]

    wrapper = ParryOpenAI(api_key="fake")
    assert wrapper.models.list() == ["gpt-4o"]
