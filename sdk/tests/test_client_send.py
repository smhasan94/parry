"""Tests for ParryClient.send_event — fire-and-forget, fail-open behavior."""
import threading
import time
from unittest.mock import MagicMock, patch

from parry.client import ParryClient


def test_send_event_fires_in_background():
    """send_event dispatches a background thread and doesn't block."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post.return_value = MagicMock(status_code=202)

        start = time.monotonic()
        client.send_event(prompt="hello", response="world", model="gpt-4o")
        elapsed = time.monotonic() - start

        # Should return near-instantly (thread dispatched, not awaited)
        assert elapsed < 0.1

        # Wait for background thread to finish
        time.sleep(0.2)
        mock_http.post.assert_called_once()
        payload = mock_http.post.call_args[1]["json"]
        assert payload["agent_id"] == "agent-1"
        assert payload["prompt"] == "hello"
        assert payload["response"] == "world"


def test_send_event_skips_without_agent_id():
    """send_event with no agent_id (and no default) logs warning and returns."""
    client = ParryClient(api_key="sk-parry-test")

    with patch.object(client, "_http") as mock_http:
        client.send_event(prompt="hello")
        time.sleep(0.1)
        mock_http.post.assert_not_called()


def test_send_event_per_call_agent_id_overrides_default():
    """Per-call agent_id takes precedence over default_agent_id."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="default-agent")

    with patch.object(client, "_http") as mock_http:
        mock_http.post.return_value = MagicMock(status_code=202)
        client.send_event(agent_id="override-agent", prompt="hello")
        time.sleep(0.2)

        payload = mock_http.post.call_args[1]["json"]
        assert payload["agent_id"] == "override-agent"


def test_send_event_fail_open_on_network_error():
    """Network errors are swallowed — send_event never raises."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post.side_effect = ConnectionError("backend down")

        # Should not raise
        client.send_event(prompt="hello")
        time.sleep(0.2)

        # Call was attempted
        mock_http.post.assert_called_once()


def test_send_event_fail_open_on_400():
    """4xx responses are logged but don't raise."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_resp = MagicMock(status_code=401, text="Unauthorized")
        mock_http.post.return_value = mock_resp

        client.send_event(prompt="hello")
        time.sleep(0.2)
        mock_http.post.assert_called_once()


def test_send_event_truncates_long_content():
    """Prompt and response are truncated to 4000 chars."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post.return_value = MagicMock(status_code=202)

        long_text = "x" * 10000
        client.send_event(prompt=long_text, response=long_text)
        time.sleep(0.2)

        payload = mock_http.post.call_args[1]["json"]
        assert len(payload["prompt"]) == 4000
        assert len(payload["response"]) == 4000


def test_send_event_passes_metadata():
    """Metadata dict is passed through to the payload."""
    client = ParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post.return_value = MagicMock(status_code=202)

        client.send_event(prompt="hello", metadata={"env": "test", "version": "1.0"})
        time.sleep(0.2)

        payload = mock_http.post.call_args[1]["json"]
        assert payload["metadata"] == {"env": "test", "version": "1.0"}
