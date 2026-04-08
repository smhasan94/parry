"""Unit tests for session_service pure helpers.

DB-backed get_session_with_events / list_agent_sessions run against a
real Postgres in e2e tests. Here we lock down the pure bits: preview
truncation and the role-aware event serializer (viewer previews only,
admin gets full content).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import AgentEvent, Detection, Severity
from app.services.session_service import (
    PREVIEW_CHARS,
    _preview,
    _serialize_event,
)


def _event(prompt: str | None = "hi", response: str | None = "hello") -> AgentEvent:
    return AgentEvent(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        prompt=prompt,
        response=response,
        model="gpt-4o",
        tool_calls=[{"name": "web_search"}],
        latency_ms=123,
        token_count=45,
    )


def _detection(triggered: bool = True, confidence: float = 0.9) -> Detection:
    return Detection(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        detector="prompt_injection",
        severity=Severity.HIGH,
        confidence=confidence,
        reason="ignore previous instructions",
        triggered=triggered,
    )


# ── preview ──────────────────────────────────────────────────────────


def test_preview_none_is_passthrough() -> None:
    assert _preview(None) is None


def test_preview_short_string_unchanged() -> None:
    assert _preview("short") == "short"


def test_preview_truncates_with_ellipsis() -> None:
    long = "x" * (PREVIEW_CHARS + 50)
    out = _preview(long)
    assert out is not None
    assert out.endswith("…")
    assert len(out) == PREVIEW_CHARS + 1  # 200 chars + ellipsis


# ── _serialize_event ─────────────────────────────────────────────────


def test_serialize_event_viewer_omits_full_content() -> None:
    evt = _event(prompt="x" * 500, response="y" * 500)
    payload = _serialize_event(evt, [], include_content=False)
    assert "prompt" not in payload
    assert "response" not in payload
    # Previews are always present regardless of role
    assert payload["prompt_preview"].endswith("…")
    assert payload["response_preview"].endswith("…")


def test_serialize_event_admin_includes_full_content() -> None:
    evt = _event(prompt="full prompt text", response="full response text")
    payload = _serialize_event(evt, [], include_content=True)
    assert payload["prompt"] == "full prompt text"
    assert payload["response"] == "full response text"
    # Previews still included for consistent rendering
    assert payload["prompt_preview"] == "full prompt text"


def test_serialize_event_sorts_detections_by_confidence_desc() -> None:
    evt = _event()
    low = _detection(confidence=0.55)
    high = _detection(confidence=0.95)
    mid = _detection(confidence=0.75)
    payload = _serialize_event(evt, [low, high, mid], include_content=False)
    confidences = [d["confidence"] for d in payload["detections"]]
    assert confidences == [0.95, 0.75, 0.55]


def test_serialize_event_carries_non_content_fields() -> None:
    evt = _event()
    payload = _serialize_event(evt, [], include_content=False)
    assert payload["model"] == "gpt-4o"
    assert payload["latency_ms"] == 123
    assert payload["token_count"] == 45
    assert payload["tool_calls"] == [{"name": "web_search"}]


def test_serialize_event_handles_null_prompt_and_response() -> None:
    evt = _event(prompt=None, response=None)
    payload = _serialize_event(evt, [], include_content=True)
    assert payload["prompt_preview"] is None
    assert payload["response_preview"] is None
    assert payload["prompt"] is None
    assert payload["response"] is None
