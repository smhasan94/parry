"""Parry SDK — AI Agent Runtime Security."""

from parry.client import ParryClient

__version__ = "0.1.0"

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
