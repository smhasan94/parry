"""Core interception logic used by all wrappers."""

import re
import time
from typing import Any

import parry

# PII patterns to strip before sending to backend
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "[CREDIT_CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
]


def strip_pii(text: str | None) -> str | None:
    if text is None:
        return None
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def intercept_completion(
    prompt: str | None,
    response: str | None,
    model: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    token_count: int | None = None,
    latency_ms: int | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Called by wrappers after every LLM completion. Strips PII and sends to Parry."""
    try:
        client = parry.get_client()
    except RuntimeError:
        return  # SDK not initialized — skip silently

    client.send_event(
        agent_id=agent_id,
        session_id=session_id,
        prompt=strip_pii(prompt),
        response=strip_pii(response),
        model=model,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
        token_count=token_count,
        metadata=metadata,
    )


class TimingContext:
    """Simple context manager to measure call latency."""

    def __init__(self) -> None:
        self.start: float = 0
        self.latency_ms: int = 0

    def __enter__(self) -> "TimingContext":
        self.start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        self.latency_ms = int((time.monotonic() - self.start) * 1000)
