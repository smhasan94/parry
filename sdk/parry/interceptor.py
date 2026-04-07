"""Core interception logic used by all wrappers."""

import logging
import re
import time
from typing import Any

import parry

logger = logging.getLogger("parry")

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
    """Called by wrappers after every LLM completion. Strips PII and sends to Parry.

    Fail-open contract: this function MUST NEVER raise. The host app's LLM
    call already succeeded by the time we're called — any failure here
    (PII regex blowup, uninitialized SDK, client attribute error, anything)
    must be swallowed and logged. _send_event_sync has its own broad catch
    but it runs on a background thread; strip_pii and client lookup happen
    on the caller's thread and would otherwise leak into the wrapper.
    """
    try:
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
    except Exception:
        logger.warning("parry.intercept_failed", exc_info=True)


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
