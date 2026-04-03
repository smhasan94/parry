"""Tests for ParryCallbackHandler — LangChain integration."""
import uuid
from unittest.mock import MagicMock, patch

import parry
from parry.wrappers.langchain import ParryCallbackHandler


def _make_llm_result(text: str = "Hello!", token_usage: dict | None = None, message=None):
    """Build an LLMResult with real Generation objects (Pydantic-validated)."""
    from langchain_core.outputs import ChatGeneration, Generation, LLMResult
    from langchain_core.messages import AIMessage

    llm_output = None
    if token_usage:
        llm_output = {"token_usage": token_usage}

    if message is not None:
        gen = ChatGeneration(text=text, message=message)
    else:
        gen = Generation(text=text)

    return LLMResult(generations=[[gen]], llm_output=llm_output)


def _make_base_message(content: str, role: str = "human"):
    msg = MagicMock()
    msg.content = content
    msg.type = role
    return msg


@patch("parry.wrappers.langchain.intercept_completion")
def test_chat_model_start_and_end(mock_intercept):
    """on_chat_model_start captures prompt, on_llm_end sends to Parry."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    run_id = uuid.uuid4()
    serialized = {"kwargs": {"model_name": "gpt-4o"}, "id": ["ChatOpenAI"]}
    messages = [[_make_base_message("What is 2+2?")]]

    handler.on_chat_model_start(serialized, messages, run_id=run_id)
    handler.on_llm_end(
        _make_llm_result("4", token_usage={"total_tokens": 15}),
        run_id=run_id,
    )

    mock_intercept.assert_called_once()
    kw = mock_intercept.call_args[1]
    assert kw["prompt"] == "What is 2+2?"
    assert kw["response"] == "4"
    assert kw["model"] == "gpt-4o"
    assert kw["token_count"] == 15
    assert kw["agent_id"] == "test-agent"
    assert kw["latency_ms"] is not None


@patch("parry.wrappers.langchain.intercept_completion")
def test_llm_start_fallback(mock_intercept):
    """on_llm_start works for plain LLMs (non-chat)."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    run_id = uuid.uuid4()
    serialized = {"kwargs": {"model": "text-davinci-003"}, "id": ["OpenAI"]}

    handler.on_llm_start(serialized, ["Translate: hello"], run_id=run_id)
    handler.on_llm_end(_make_llm_result("hola"), run_id=run_id)

    kw = mock_intercept.call_args[1]
    assert kw["prompt"] == "Translate: hello"
    assert kw["response"] == "hola"
    assert kw["model"] == "text-davinci-003"


@patch("parry.wrappers.langchain.intercept_completion")
def test_tool_calls_from_message(mock_intercept):
    """Tool calls in AIMessage are extracted."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    run_id = uuid.uuid4()
    serialized = {"kwargs": {"model_name": "gpt-4o"}, "id": ["ChatOpenAI"]}

    handler.on_chat_model_start(serialized, [[_make_base_message("Search weather")]], run_id=run_id)

    # Simulate AIMessage with tool_calls
    from langchain_core.messages import AIMessage

    ai_message = AIMessage(
        content="I'll search for that.",
        tool_calls=[{"name": "search", "args": {"query": "weather today"}, "id": "tc1", "type": "tool_call"}],
    )

    handler.on_llm_end(
        _make_llm_result("I'll search for that.", message=ai_message),
        run_id=run_id,
    )

    kw = mock_intercept.call_args[1]
    assert kw["tool_calls"] is not None
    assert len(kw["tool_calls"]) == 1
    assert kw["tool_calls"][0]["name"] == "search"
    assert kw["tool_calls"][0]["arguments"] == {"query": "weather today"}


@patch("parry.wrappers.langchain.intercept_completion")
def test_tool_start_tracks_calls(mock_intercept):
    """on_tool_start adds tool calls to the parent LLM run."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    llm_run_id = uuid.uuid4()
    tool_run_id = uuid.uuid4()

    serialized = {"kwargs": {"model_name": "gpt-4o"}, "id": ["ChatOpenAI"]}
    handler.on_chat_model_start(serialized, [[_make_base_message("Do something")]], run_id=llm_run_id)

    handler.on_tool_start(
        {"name": "calculator"},
        "2+2",
        run_id=tool_run_id,
        parent_run_id=llm_run_id,
        inputs={"expression": "2+2"},
    )

    handler.on_llm_end(_make_llm_result("Done"), run_id=llm_run_id)

    kw = mock_intercept.call_args[1]
    assert kw["tool_calls"] is not None
    assert kw["tool_calls"][0]["name"] == "calculator"


@patch("parry.wrappers.langchain.intercept_completion")
def test_llm_error_cleans_up(mock_intercept):
    """on_llm_error removes run state without sending."""
    handler = ParryCallbackHandler(agent_id="test-agent")
    run_id = uuid.uuid4()

    serialized = {"kwargs": {}, "id": ["ChatOpenAI"]}
    handler.on_chat_model_start(serialized, [[_make_base_message("test")]], run_id=run_id)

    assert run_id in handler._runs
    handler.on_llm_error(RuntimeError("fail"), run_id=run_id)

    assert run_id not in handler._runs
    mock_intercept.assert_not_called()


@patch("parry.wrappers.langchain.intercept_completion")
def test_unknown_run_id_on_end(mock_intercept):
    """on_llm_end with unknown run_id is a no-op."""
    handler = ParryCallbackHandler(agent_id="test-agent")
    handler.on_llm_end(_make_llm_result("test"), run_id=uuid.uuid4())
    mock_intercept.assert_not_called()


@patch("parry.wrappers.langchain.intercept_completion")
def test_session_id_passed_through(mock_intercept):
    """session_id from handler init is passed to intercept."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent", session_id="sess-123")

    run_id = uuid.uuid4()
    serialized = {"kwargs": {"model_name": "gpt-4o"}, "id": ["ChatOpenAI"]}
    handler.on_chat_model_start(serialized, [[_make_base_message("hi")]], run_id=run_id)
    handler.on_llm_end(_make_llm_result("hello"), run_id=run_id)

    kw = mock_intercept.call_args[1]
    assert kw["session_id"] == "sess-123"


@patch("parry.wrappers.langchain.intercept_completion")
def test_model_name_from_id_fallback(mock_intercept):
    """Model name extracted from serialized.id when kwargs doesn't have it."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    run_id = uuid.uuid4()
    serialized = {"kwargs": {}, "id": ["langchain", "chat_models", "ChatAnthropic"]}
    handler.on_chat_model_start(serialized, [[_make_base_message("hi")]], run_id=run_id)
    handler.on_llm_end(_make_llm_result("hello"), run_id=run_id)

    kw = mock_intercept.call_args[1]
    assert kw["model"] == "ChatAnthropic"


@patch("parry.wrappers.langchain.intercept_completion")
def test_block_content_messages(mock_intercept):
    """Messages with list content (image+text blocks) extract text correctly."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="test-agent")

    msg = MagicMock()
    msg.content = [{"type": "text", "text": "Describe this"}, {"type": "image_url", "url": "..."}]

    run_id = uuid.uuid4()
    serialized = {"kwargs": {"model_name": "gpt-4o"}, "id": ["ChatOpenAI"]}
    handler.on_chat_model_start(serialized, [[msg]], run_id=run_id)
    handler.on_llm_end(_make_llm_result("A cat"), run_id=run_id)

    kw = mock_intercept.call_args[1]
    assert kw["prompt"] == "Describe this"
