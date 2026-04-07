"""Fail-open regression tests.

Contract: no matter what goes wrong inside Parry's interception layer —
PII regex failure, uninitialized SDK, broken backend client, slow backend,
anything — the host app's LLM call MUST return normally and on time.
These tests exist to prevent a future refactor from quietly
reintroducing an exception leak or a sync blocking call.
"""
import time
import uuid
from unittest.mock import MagicMock, patch

import parry
from parry import interceptor
from parry.wrappers.anthropic import ParryAnthropic
from parry.wrappers.langchain import ParryCallbackHandler
from parry.wrappers.openai import ParryOpenAI


# ── interceptor.intercept_completion itself ───────────────────────────

def test_intercept_swallows_strip_pii_error(caplog):
    """If strip_pii blows up (e.g. catastrophic regex backtracking),
    intercept_completion must not raise into its caller."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    with patch.object(interceptor, "strip_pii", side_effect=RuntimeError("regex boom")):
        # Would have raised pre-hardening
        interceptor.intercept_completion(prompt="hi", response="hello")
    # And we should see the warning log
    assert any("intercept_failed" in r.message for r in caplog.records)


def test_intercept_swallows_client_error():
    """If get_client() returns a client whose send_event blows up,
    intercept_completion must not raise."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    bad_client = MagicMock()
    bad_client.send_event.side_effect = RuntimeError("backend dead")
    with patch.object(parry, "get_client", return_value=bad_client):
        interceptor.intercept_completion(prompt="hi", response="hello")


# ── OpenAI wrapper ────────────────────────────────────────────────────

def _mock_openai_response(content: str = "ok"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    usage = MagicMock()
    usage.total_tokens = 10
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


@patch("parry.wrappers.openai.intercept_completion", side_effect=RuntimeError("boom"))
@patch("openai.OpenAI")
def test_openai_wrapper_returns_response_even_if_intercept_raises(
    MockOpenAI, _mock_intercept
):
    MockOpenAI.return_value.chat.completions.create.return_value = _mock_openai_response(
        "Paris."
    )
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="a", api_key="fake")

    result = wrapper.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "?"}]
    )
    assert result.choices[0].message.content == "Paris."


# ── Anthropic wrapper ─────────────────────────────────────────────────

def _mock_anthropic_response(text: str = "ok"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    usage = MagicMock()
    usage.input_tokens = 5
    usage.output_tokens = 5
    resp = MagicMock()
    resp.content = [block]
    resp.usage = usage
    return resp


@patch("parry.wrappers.anthropic.intercept_completion", side_effect=RuntimeError("boom"))
@patch("anthropic.Anthropic")
def test_anthropic_wrapper_returns_response_even_if_intercept_raises(
    MockAnthropic, _mock_intercept
):
    MockAnthropic.return_value.messages.create.return_value = _mock_anthropic_response(
        "hola"
    )
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryAnthropic(agent_id="a", api_key="fake")

    result = wrapper.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.content[0].text == "hola"


# ── Slow backend must not block the wrapper ──────────────────────────

@patch("openai.OpenAI")
def test_slow_backend_does_not_block_openai_wrapper(MockOpenAI):
    """Fire-and-forget contract: if the Parry backend sleeps for seconds,
    the wrapper must still return within a few ms. Regression guard
    against someone switching ParryClient to a sync/awaited send path."""
    MockOpenAI.return_value.chat.completions.create.return_value = _mock_openai_response(
        "fast"
    )

    def slow_post(*args, **kwargs):
        time.sleep(2.0)  # simulate a backend hang
        resp = MagicMock()
        resp.status_code = 202
        resp.text = ""
        return resp

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="a", api_key="fake")

    with patch.object(
        parry.get_client()._http, "post", side_effect=slow_post
    ):
        started = time.monotonic()
        result = wrapper.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "?"}]
        )
        elapsed = time.monotonic() - started

    assert result.choices[0].message.content == "fast"
    # Fire-and-forget should return in well under the 2s backend sleep.
    # Allow 500ms headroom for CI jitter / thread spawn.
    assert elapsed < 0.5, f"wrapper blocked for {elapsed:.2f}s — fire-and-forget broken"


# ── Host raises mid-stream ────────────────────────────────────────────

def _make_openai_stream_chunks(texts: list[str]):
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
def test_host_exception_mid_stream_propagates_cleanly(MockOpenAI, mock_intercept):
    """If the host aborts iteration over a streaming response, the original
    exception must reach the host unchanged and Parry must not raise a
    secondary exception. Interception is skipped (no cleanup hook) which
    is acceptable — the host already has a bigger problem."""
    MockOpenAI.return_value.chat.completions.create.return_value = iter(
        _make_openai_stream_chunks(["hel", "lo"])
    )
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    wrapper = ParryOpenAI(agent_id="a", api_key="fake")

    stream = wrapper.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    host_error = RuntimeError("host blew up mid-stream")
    raised = None
    try:
        for _chunk in stream:
            raise host_error
    except RuntimeError as e:
        raised = e

    # Host's exception reaches the host unchanged
    assert raised is host_error
    # And interception was skipped (the generator never finished)
    mock_intercept.assert_not_called()


# ── Malformed backend response ────────────────────────────────────────

def test_client_survives_malformed_backend_response():
    """Backend returns a 500 with HTML garbage — _send_event_sync must
    log and swallow, never raise. Uses the real client send path so we
    exercise the actual except block."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    client = parry.get_client()

    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad_resp.text = "<html><body>nginx crashed</body></html>"

    with patch.object(client._http, "post", return_value=bad_resp):
        # Runs on background thread, but the sync helper is callable directly
        client._send_event_sync({"agent_id": "a", "prompt": "hi"})
    # No assertion needed — the test passes if _send_event_sync returned
    # without raising. The broad except already logs.


def test_client_survives_post_raising_unexpected_exception():
    """httpx.post raising something weird (not a normal network error)
    must still be swallowed — regression guard on the broad except."""
    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    client = parry.get_client()

    with patch.object(client._http, "post", side_effect=ValueError("weird")):
        client._send_event_sync({"agent_id": "a", "prompt": "hi"})


# ── LangChain callback ────────────────────────────────────────────────

@patch("parry.wrappers.langchain.intercept_completion", side_effect=RuntimeError("boom"))
def test_langchain_callback_swallows_intercept_error(_mock_intercept):
    """LangChain's runtime calls on_llm_end synchronously on the host thread;
    an exception there would crash the chain. Verify it's swallowed."""
    from langchain_core.outputs import Generation, LLMResult

    parry.init(api_key="sk-parry-test", base_url="http://localhost:8000")
    handler = ParryCallbackHandler(agent_id="a")

    run_id = uuid.uuid4()
    handler.on_llm_start(
        {"kwargs": {"model": "gpt-4o"}, "id": ["OpenAI"]},
        ["hi"],
        run_id=run_id,
    )

    # Should not raise — intercept_completion is patched to blow up but the
    # hardened interceptor (or the callback's own guard, if we add one) must
    # swallow it. This is the regression guard.
    handler.on_llm_end(
        LLMResult(generations=[[Generation(text="4")]]),
        run_id=run_id,
    )
