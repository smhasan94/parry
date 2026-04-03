"""Tests for AsyncParryClient."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parry.async_client import AsyncParryClient, _truncate


@pytest.mark.asyncio
async def test_send_event_fires_background_task():
    """send_event creates a background task that calls the API."""
    client = AsyncParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock(return_value=MagicMock(status_code=202))

        await client.send_event(prompt="hello", response="world", model="gpt-4o")
        # Let the background task run
        await asyncio.sleep(0.05)

        mock_http.post.assert_called_once()
        payload = mock_http.post.call_args[1]["json"]
        assert payload["agent_id"] == "agent-1"
        assert payload["prompt"] == "hello"


@pytest.mark.asyncio
async def test_send_event_skips_without_agent_id():
    """send_event with no agent_id is a no-op."""
    client = AsyncParryClient(api_key="sk-parry-test")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock()
        await client.send_event(prompt="hello")
        await asyncio.sleep(0.05)
        mock_http.post.assert_not_called()


@pytest.mark.asyncio
async def test_send_event_per_call_agent_id():
    """Per-call agent_id overrides default."""
    client = AsyncParryClient(api_key="sk-parry-test", default_agent_id="default")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock(return_value=MagicMock(status_code=202))
        await client.send_event(agent_id="override", prompt="hello")
        await asyncio.sleep(0.05)

        payload = mock_http.post.call_args[1]["json"]
        assert payload["agent_id"] == "override"


@pytest.mark.asyncio
async def test_send_event_fail_open():
    """Network errors are swallowed — never raises."""
    client = AsyncParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock(side_effect=ConnectionError("timeout"))
        await client.send_event(prompt="hello")
        await asyncio.sleep(0.05)
        # Should not raise — error is logged and swallowed


@pytest.mark.asyncio
async def test_send_event_blocking():
    """send_event_blocking awaits the send."""
    client = AsyncParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock(return_value=MagicMock(status_code=202))
        await client.send_event_blocking(prompt="hello")
        mock_http.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_event_truncates():
    """Long prompt/response are truncated to 4000 chars."""
    client = AsyncParryClient(api_key="sk-parry-test", default_agent_id="agent-1")

    with patch.object(client, "_http") as mock_http:
        mock_http.post = AsyncMock(return_value=MagicMock(status_code=202))
        await client.send_event(prompt="x" * 10000, response="y" * 10000)
        await asyncio.sleep(0.05)

        payload = mock_http.post.call_args[1]["json"]
        assert len(payload["prompt"]) == 4000
        assert len(payload["response"]) == 4000


def test_truncate():
    assert _truncate(None, 100) is None
    assert _truncate("short", 100) == "short"
    assert len(_truncate("x" * 200, 100)) == 100
