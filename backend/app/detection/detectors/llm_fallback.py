"""LLM fallback detector — calls Claude to resolve ambiguous detection scores."""

import asyncio
import json
import time
from typing import Any

import structlog

from app.core.metrics import record_llm_fallback_call
from app.db.models import Severity
from app.detection.base import DetectionResult

log = structlog.get_logger()

# Hard cap on the Anthropic call. The Celery detection task has a 30s
# soft limit; we stay comfortably under it so a hanging API call burns
# its own timeout slot rather than killing the worker process.
ANTHROPIC_TIMEOUT_SECONDS = 20.0

# Claude Sonnet 4.6 pricing, USD per 1M tokens. Update when Anthropic
# publishes new rates — intentionally kept as plain constants so the
# value shows up in `git blame` rather than being hidden in a config file.
PRICE_PER_M_INPUT_USD = 3.0
PRICE_PER_M_OUTPUT_USD = 15.0


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens * PRICE_PER_M_INPUT_USD
         + output_tokens * PRICE_PER_M_OUTPUT_USD) / 1_000_000,
        6,
    )

SYSTEM_PROMPT = """You are a security analyst for an AI agent monitoring system called Parry.
Your job is to analyze an AI agent's LLM call and determine if it represents a security threat.

You will be given:
- The prompt sent to the LLM
- The response from the LLM
- The model used
- Any tool calls made
- Which detectors flagged this as ambiguous and why

Respond with a JSON object:
{
  "is_threat": true/false,
  "severity": "critical" | "high" | "medium" | "low",
  "reason": "one sentence explaining your judgment",
  "confidence": 0.0 to 1.0
}

Be conservative — only flag genuine security threats. Normal conversations about security topics
are NOT threats. Focus on actual prompt injection, data exfiltration, privilege escalation, or
tool misuse attempts."""


async def evaluate_ambiguous(
    event_data: dict[str, Any],
    ambiguous_results: list[DetectionResult],
) -> DetectionResult | None:
    """Call Claude to evaluate ambiguous detection results.

    Returns a DetectionResult if Claude confirms a threat, None otherwise.
    Returns None silently if the API key is not configured.
    """
    from app.core.config import settings

    if not settings.anthropic_api_key:
        log.debug("llm_fallback.skipped", reason="no API key configured")
        record_llm_fallback_call("no_key")
        return None

    # Build the analysis prompt
    ambiguous_summary = "\n".join(
        f"- [{r.detector}] confidence={r.confidence:.2f}: {r.reason}" for r in ambiguous_results
    )

    user_prompt = f"""Analyze this AI agent LLM call for security threats:

**Prompt:** {(event_data.get("prompt") or "")[:1000]}

**Response:** {(event_data.get("response") or "")[:1000]}

**Model:** {event_data.get("model") or "unknown"}

**Tool calls:** {json.dumps(event_data.get("tool_calls") or [], default=str)[:500]}

**Ambiguous detections (need your judgment):**
{ambiguous_summary}

Respond with JSON only."""

    response_text = ""
    input_tokens = 0
    output_tokens = 0
    started = time.monotonic()

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        # Wrap in asyncio.wait_for so even if the Anthropic SDK's own
        # timeout is misconfigured, we cap wall time at ANTHROPIC_TIMEOUT_SECONDS.
        message = await asyncio.wait_for(
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            ),
            timeout=ANTHROPIC_TIMEOUT_SECONDS,
        )

        # Parse response
        response_text = message.content[0].text if message.content else ""
        if getattr(message, "usage", None):
            input_tokens = int(getattr(message.usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(message.usage, "output_tokens", 0) or 0)

        result = json.loads(response_text)

        is_threat = result.get("is_threat", False)
        latency = time.monotonic() - started

        cost_usd = _estimate_cost_usd(input_tokens, output_tokens)

        if not is_threat:
            log.info(
                "llm_fallback.cleared",
                reason=result.get("reason", ""),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
            record_llm_fallback_call(
                "cleared", input_tokens, output_tokens, latency, cost_usd
            )
            return None

        severity_map = {
            "critical": Severity.CRITICAL,
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
        }

        record_llm_fallback_call(
            "confirmed", input_tokens, output_tokens, latency, cost_usd
        )

        return DetectionResult(
            triggered=True,
            severity=severity_map.get(result.get("severity", "medium"), Severity.MEDIUM),
            confidence=min(float(result.get("confidence", 0.7)), 1.0),
            reason=result.get("reason", "LLM fallback flagged as threat"),
            detector="llm_fallback",
            details={
                "ambiguous_detectors": [r.detector for r in ambiguous_results],
                "llm_judgment": result,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            },
        )

    except TimeoutError:
        log.warning(
            "llm_fallback.timeout", timeout_seconds=ANTHROPIC_TIMEOUT_SECONDS
        )
        record_llm_fallback_call(
            "timeout",
            input_tokens,
            output_tokens,
            time.monotonic() - started,
        )
        return None
    except json.JSONDecodeError:
        log.warning("llm_fallback.parse_error", response=response_text[:200])
        record_llm_fallback_call(
            "parse_error",
            input_tokens,
            output_tokens,
            time.monotonic() - started,
        )
        return None
    except Exception:
        log.warning("llm_fallback.failed", exc_info=True)
        record_llm_fallback_call(
            "api_error",
            input_tokens,
            output_tokens,
            time.monotonic() - started,
        )
        return None
