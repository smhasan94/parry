"""Read tool-call arguments as scannable text, under a size bound.

Two things made argument content invisible to the detectors. The call
shape differs per SDK — the OpenAI wrapper sends ``arguments`` as a
JSON *string*, Anthropic and LangChain send dicts, and the corpora use
``args`` — so a detector reading one key silently saw nothing for the
other two.

The bound is the second reason. ``ProxyCheckRequest`` caps neither the
number of tool calls nor the size of their arguments, so scanning them
whole reopens on the blocking path exactly the DoS that bounding the
prompt window closed: pattern scanning is linear in input length, and
an attacker choosing that length controls the latency.

Truncation is per call *and* in total. A per-call cap alone still lets
a thousand calls of that size through, and a total alone lets one call
spend the whole budget while the rest go unscanned.
"""

from __future__ import annotations

import json
from typing import Any

# Sized against the <10ms budget of app.proxy.check: the same order as
# the prompt window, since this text runs through the same patterns.
# Prefer shrinking the per-call cap over MAX_BLOCKING_SCAN_CHARS if the
# with-tools path ever exceeds budget — a real call's arguments run to
# hundreds of characters, not thousands.
MAX_ARG_CHARS_PER_CALL = 2_000
MAX_ARG_CHARS_TOTAL = 8_000

# Keys carrying arguments across the SDK wrappers and the corpora.
# Order matters only in that the first present key wins.
_ARG_KEYS = ("arguments", "args", "input", "parameters")


def call_arg_text(call: dict[str, Any], cap: int = MAX_ARG_CHARS_PER_CALL) -> str:
    """Return one tool call's arguments as text, truncated to ``cap``."""
    raw: Any = None
    for key in _ARG_KEYS:
        if key in call and call[key] not in (None, "", {}, []):
            raw = call[key]
            break

    if raw is None:
        function = call.get("function")
        if isinstance(function, dict):
            raw = function.get("arguments")

    if raw is None:
        return ""

    if isinstance(raw, str):
        text = raw
    else:
        try:
            text = json.dumps(raw, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(raw)

    return text[:cap]


def arg_text(
    tool_calls: list[dict[str, Any]],
    per_call: int = MAX_ARG_CHARS_PER_CALL,
    total: int = MAX_ARG_CHARS_TOTAL,
) -> str:
    """Return every call's arguments as one newline-joined block.

    Joined with a newline rather than concatenated so two calls cannot
    fabricate a phrase that appears in neither — the same reason the
    bounded prompt window splices an elision marker between its slices.
    """
    parts: list[str] = []
    budget = total

    for call in tool_calls:
        if budget <= 0:
            break
        if not isinstance(call, dict):
            continue
        text = call_arg_text(call, cap=min(per_call, budget))
        if not text:
            continue
        parts.append(text)
        budget -= len(text)

    return "\n".join(parts)
