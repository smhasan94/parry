"""Parry SDK — AI Agent Runtime Security."""

from parry.async_client import AsyncParryClient
from parry.blocking import ParryBlockedError, ParryPermissionDeniedError
from parry.client import ParryClient
from parry.wrappers.anthropic import ParryAnthropic
from parry.wrappers.langchain import ParryCallbackHandler
from parry.wrappers.openai import ParryOpenAI

__version__ = "0.1.0"

__all__ = [
    "AsyncParryClient",
    "ParryAnthropic",
    "ParryBlockedError",
    "ParryCallbackHandler",
    "ParryClient",
    "ParryOpenAI",
    "ParryPermissionDeniedError",
    "auto_instrument",
    "get_client",
    "init",
]

from parry.middleware.auto_instrument import auto_instrument

_client: ParryClient | None = None


def init(
    api_key: str,
    base_url: str = "https://api.parry.dev",
    agent_id: str | None = None,
) -> ParryClient:
    """Initialize the Parry SDK.

    Usage:
        import parry
        parry.init(api_key="sk-parry-...")
    """
    global _client
    _client = ParryClient(api_key=api_key, base_url=base_url, default_agent_id=agent_id)
    return _client


def get_client() -> ParryClient:
    if _client is None:
        raise RuntimeError("Parry SDK not initialized. Call parry.init(api_key=...) first.")
    return _client
