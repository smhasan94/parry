"""Synchronous pre-call blocking check for the Parry proxy mode.

Unlike the fire-and-forget event ingest path, this module intentionally
makes a blocking HTTP call on the caller's thread — the whole point of
blocking mode is that the LLM call doesn't happen until the proxy
verdict is in. To keep the user-visible latency acceptable:

- Hard 2s timeout. If the proxy hasn't answered by then, fail open.
- Fail-open contract. ANY error other than an explicit block means
  the call proceeds. Parry must never be the reason a valid LLM call
  gets dropped.
- Errors are logged as warnings, never re-raised.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("parry")

PROXY_CHECK_TIMEOUT_SECONDS = 2.0


class ParryBlockedError(Exception):
    """Raised by the SDK wrappers when the Parry proxy rejects an LLM call.

    Catch this in your agent code to decide how to handle a policy
    block — re-prompt the user, log it, return a canned refusal, etc.
    The attributes mirror the JSON contract from /api/v1/proxy/check.
    """

    def __init__(
        self,
        reason: str,
        detector: str,
        severity: str,
        confidence: float,
    ) -> None:
        self.reason = reason
        self.detector = detector
        self.severity = severity
        self.confidence = confidence
        super().__init__(f"Parry blocked this call: [{detector}] {reason}")


class ParryPermissionDeniedError(ParryBlockedError):
    """Raised when an agent's tool call is denied by a permission boundary.

    Distinct from ParryBlockedError (threat detection) so agent code
    can handle authorization failures differently from security blocks.

    Example::

        try:
            response = openai_client.chat.completions.create(...)
        except ParryPermissionDeniedError as e:
            print(f"Agent not authorized to call {e.tool_name}: {e.reason}")
        except ParryBlockedError as e:
            print(f"Security block: {e.reason}")
    """

    def __init__(
        self,
        reason: str,
        tool_name: str | None = None,
        **kwargs: object,
    ) -> None:
        self.tool_name = tool_name
        super().__init__(
            reason=reason,
            detector="permission_boundary",
            severity="high",
            confidence=1.0,
        )


def check_before_call(
    client: Any,  # ParryClient instance — Any to avoid circular import
    prompt: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    model: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Call /api/v1/proxy/check synchronously. Raises ParryBlockedError if blocked.

    Any other failure — network error, timeout, non-200 status, malformed
    response — results in the call being allowed through (fail open).
    """
    if client is None:
        return

    payload = {
        "agent_id": agent_id or getattr(client, "default_agent_id", None),
        "session_id": session_id,
        "prompt": prompt,
        "model": model,
        "tool_calls": tool_calls or [],
    }

    try:
        resp = client._http.post(
            "/api/v1/proxy/check",
            json=payload,
            timeout=PROXY_CHECK_TIMEOUT_SECONDS,
        )
    except ParryBlockedError:
        raise
    except Exception:
        logger.warning("parry: proxy check failed, failing open", exc_info=True)
        return

    if resp.status_code != 200:
        logger.warning("parry: proxy check returned %s, failing open", resp.status_code)
        return

    try:
        data = resp.json()
    except Exception:
        logger.warning("parry: proxy check returned non-JSON, failing open", exc_info=True)
        return

    if not data.get("allowed", True):
        detector = data.get("detector", "")
        reason = data.get("reason", "")
        if detector == "permission_boundary":
            raise ParryPermissionDeniedError(
                reason=reason,
                tool_name=_extract_tool_name(reason),
            )
        raise ParryBlockedError(
            reason=reason,
            detector=detector,
            severity=data.get("severity") or "",
            confidence=float(data.get("confidence", 0.0) or 0.0),
        )


def _extract_tool_name(reason: str) -> str | None:
    """Best-effort extract tool name from permission denial reason."""
    # Reason format: "Tool 'get_weather' is explicitly blocked"
    if "'" in reason:
        parts = reason.split("'")
        if len(parts) >= 2:
            return parts[1]
    return None
