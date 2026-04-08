"""Post-LLM response scanning via the Parry proxy.

Called by the SDK wrappers AFTER the LLM returns but BEFORE the
response is handed to the host agent. The backend decides based on
org config whether to:

- pass the response through unchanged (mode=off, or no sensitive data found)
- return a redacted copy with sensitive patterns replaced (mode=redact)
- block the whole response by raising ParryBlockedError (mode=block)

Contract:
- 2 second timeout. The scan is in the agent's user-visible latency
  path so we budget it tight.
- Fail open on ANY error except an explicit block verdict — a network
  hiccup or a 500 from the scanner must not corrupt the agent's
  response by dropping it.
"""

from __future__ import annotations

import logging
from typing import Any

from parry.blocking import ParryBlockedError

logger = logging.getLogger("parry")

SCAN_TIMEOUT_SECONDS = 2.0


def scan_response_before_return(
    client: Any,
    response_text: str | None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> str | None:
    """Call /api/v1/proxy/scan-response. Returns the (possibly redacted)
    response text. Raises ParryBlockedError only when the backend
    explicitly sets blocked=true. All other failures fall through and
    return the original text unchanged."""
    if client is None or not response_text:
        return response_text

    payload = {
        "agent_id": agent_id or getattr(client, "default_agent_id", None),
        "session_id": session_id,
        "response": response_text,
    }

    try:
        resp = client._http.post(
            "/api/v1/proxy/scan-response",
            json=payload,
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except ParryBlockedError:
        raise
    except Exception:
        logger.warning("parry: response scan failed, failing open", exc_info=True)
        return response_text

    if resp.status_code != 200:
        logger.warning("parry: response scan returned %s, failing open", resp.status_code)
        return response_text

    try:
        data = resp.json()
    except Exception:
        logger.warning("parry: response scan returned non-JSON, failing open", exc_info=True)
        return response_text

    if data.get("blocked"):
        findings = data.get("findings") or []
        top = findings[0].get("pattern") if findings else "sensitive data"
        raise ParryBlockedError(
            reason=f"Sensitive data in response: {top}",
            detector="data_exfiltration",
            severity="high",
            confidence=0.85,
        )

    # When the backend redacted in place it returns the cleaned text;
    # otherwise `response` will equal the original.
    return data.get("response", response_text)
