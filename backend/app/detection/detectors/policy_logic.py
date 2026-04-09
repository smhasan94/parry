"""Pure policy evaluation.

Single source of truth for "does this event violate this policy?".
Used by:
- Runtime detection (future PolicyEnforcer detector)
- Policy regression simulation (`policy_regression_service.simulate_policy`)

Keeping the logic here — pure, sync, no I/O — eliminates the drift
risk between runtime enforcement and historical simulation.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s)>\"']+", re.IGNORECASE)


def _extract_domains(text: str) -> list[str]:
    """Pull bare domains out of any http(s) URLs in ``text``.

    Best-effort: drops the port and lowercases. Used for blocked-domain
    matching, so we want exact host matches against the policy list.
    """
    domains: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        try:
            host = urlparse(match.group(0)).hostname
        except ValueError:
            continue
        if host:
            domains.append(host.lower())
    return domains


def evaluate_policy(
    policy: dict[str, Any],
    event_data: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Pure policy evaluation. Returns ``(triggered, violations)``.

    ``policy`` is the partial dict shape used in `Policy` model columns
    (`blocked_tools`, `blocked_domains`, `forbidden_patterns`,
    `max_token_budget`). Missing fields are simply not enforced — this
    lets the simulator pass a delta dict to preview the effect of
    adding a single field.

    ``event_data`` mirrors the runtime detector contract: ``prompt``,
    ``response``, ``tool_calls``, ``token_count``.
    """
    violations: list[str] = []

    # ── Blocked tool invocations ─────────────────────────────────
    blocked_tools = set(policy.get("blocked_tools") or [])
    if blocked_tools:
        for call in event_data.get("tool_calls") or []:
            name = call.get("name") if isinstance(call, dict) else None
            if name and name in blocked_tools:
                violations.append(f"Blocked tool invoked: {name}")

    combined_text = f"{event_data.get('prompt') or ''}\n{event_data.get('response') or ''}"

    # ── Blocked domains ───────────────────────────────────────────
    blocked_domains = set(policy.get("blocked_domains") or [])
    if blocked_domains:
        for domain in _extract_domains(combined_text):
            if domain in blocked_domains:
                violations.append(f"Blocked domain referenced: {domain}")

    # ── Forbidden regex patterns ──────────────────────────────────
    for pattern in policy.get("forbidden_patterns") or []:
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            if re.search(pattern, combined_text, re.IGNORECASE):
                violations.append(f"Forbidden pattern matched: {pattern[:40]}")
        except re.error:
            # Defense in depth — write-path validates regex, but a
            # corrupted JSONB row shouldn't crash the simulator.
            continue

    # ── Token budget ──────────────────────────────────────────────
    max_tokens = policy.get("max_token_budget")
    if max_tokens:
        token_count = event_data.get("token_count") or 0
        if token_count > max_tokens:
            violations.append(f"Token budget exceeded: {token_count} > {max_tokens}")

    return bool(violations), violations
