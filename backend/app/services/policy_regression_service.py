"""Policy regression simulator.

Lets customers preview the effect of a custom regex rule or a policy
change against their historical events before committing. Pure read
path — no writes, no detection records — so it's safe to run on a
hot reader replica if we ever split them.

Performance budget (see plan-15-17-next-wave.md):
- 20 agents × 1k events/day × 30d = 600k events
- ~5μs per event for compiled regex search
- Hard cap: 500k events per simulation, then truncate
- Per-pattern length cap: 512 chars
- Suspicious nested-quantifier patterns rejected before compile

The service does NOT call into the live detection engine. It calls
`evaluate_policy()` directly so the simulation matches whatever the
runtime path *would* do for the same inputs.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, AgentEvent
from app.detection.detectors.policy_logic import evaluate_policy

log = structlog.get_logger()

MAX_REGEX_LENGTH = 512
MAX_SIMULATION_EVENTS = 500_000
DEFAULT_SAMPLE_LIMIT = 10
PREVIEW_LENGTH = 200

# Patterns whose nested quantifiers can blow up `re` with catastrophic
# backtracking. We reject these on input rather than relying on a
# per-event timeout (signal-based timeouts don't work in async code).
_SUSPICIOUS_PATTERNS = [
    re.compile(r"\(\.[\*\+]\?\)[\*\+]"),  # (.*?)+, (.+?)*
    re.compile(r"\([^)]*\+\)[\+\*]"),  # (a+)+
    re.compile(r"\([^)]*\*\)[\+\*]"),  # (a*)+
]


class SimulationSample(TypedDict):
    event_id: str
    agent_name: str
    timestamp: str
    matched_field: Literal["prompt", "response"]
    prompt_preview: str
    response_preview: str
    match_span: str


class SimulationReport(TypedDict):
    days_checked: int
    total_events_checked: int
    matched_count: int
    match_rate: float
    by_agent: dict[str, int]
    by_day: dict[str, int]
    samples: list[SimulationSample]
    truncated: bool
    pattern_is_valid: bool
    error: str | None


def validate_pattern(pattern: str) -> None:
    """Raise ``ValueError`` if ``pattern`` is unsafe to compile.

    Guards: length cap, regex syntax, nested-quantifier shapes that
    cause catastrophic backtracking in the stdlib `re` engine.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("Pattern must be a non-empty string")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"Pattern too long (max {MAX_REGEX_LENGTH})")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}") from e
    for bad in _SUSPICIOUS_PATTERNS:
        if bad.search(pattern):
            raise ValueError(
                "Pattern has nested quantifiers that may cause catastrophic backtracking"
            )


def _preview(text: str | None) -> str:
    if not text:
        return ""
    if len(text) <= PREVIEW_LENGTH:
        return text
    return text[:PREVIEW_LENGTH] + "…"


def _empty_report(
    days_back: int,
    *,
    error: str | None = None,
    pattern_valid: bool = True,
) -> SimulationReport:
    return {
        "days_checked": days_back,
        "total_events_checked": 0,
        "matched_count": 0,
        "match_rate": 0.0,
        "by_agent": {},
        "by_day": {},
        "samples": [],
        "truncated": False,
        "pattern_is_valid": pattern_valid,
        "error": error,
    }


def _match_event(
    compiled: re.Pattern[str],
    target: Literal["prompt", "response", "both"],
    event: AgentEvent,
) -> dict[str, str] | None:
    if target in ("prompt", "both") and event.prompt:
        m = compiled.search(event.prompt)
        if m:
            return {"field": "prompt", "span": m.group(0)[:200]}
    if target in ("response", "both") and event.response:
        m = compiled.search(event.response)
        if m:
            return {"field": "response", "span": m.group(0)[:200]}
    return None


def _sample_from(
    event: AgentEvent,
    agent_name: str,
    match: dict[str, str],
) -> SimulationSample:
    return {
        "event_id": str(event.id),
        "agent_name": agent_name,
        "timestamp": event.timestamp.isoformat() if event.timestamp else "",
        "matched_field": match["field"],  # type: ignore[typeddict-item]
        "prompt_preview": _preview(event.prompt),
        "response_preview": _preview(event.response),
        "match_span": match["span"],
    }


async def _iter_org_events(
    db: AsyncSession,
    org_id: uuid.UUID,
    since: datetime,
) -> list[tuple[Agent, list[AgentEvent]]]:
    """Load each org agent and its events newer than ``since``.

    Returned eagerly because TimescaleDB hypertables play poorly with
    long-lived async cursors across many agents — we'd rather load in
    batches per agent and let the orchestrator chunk if needed.
    """
    agents_q = await db.execute(select(Agent).where(Agent.org_id == org_id))
    agents = list(agents_q.scalars().all())

    out: list[tuple[Agent, list[AgentEvent]]] = []
    for agent in agents:
        events_q = await db.execute(
            select(AgentEvent)
            .where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.timestamp >= since,
            )
            .order_by(AgentEvent.timestamp.desc())
        )
        out.append((agent, list(events_q.scalars().all())))
    return out


async def simulate_custom_rule(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    pattern: str,
    target: Literal["prompt", "response", "both"] = "both",
    days_back: int = 30,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    max_events: int = MAX_SIMULATION_EVENTS,
) -> SimulationReport:
    """Simulate a regex rule against historical events for an org.

    Returns a `SimulationReport`. On invalid pattern returns an empty
    report with ``pattern_is_valid=False`` and an `error` string — never
    queries the DB in that case.
    """
    try:
        validate_pattern(pattern)
    except ValueError as e:
        return _empty_report(days_back, error=str(e), pattern_valid=False)

    compiled = re.compile(pattern, re.IGNORECASE)
    since = datetime.now(UTC) - timedelta(days=days_back)

    by_agent: Counter[str] = Counter()
    by_day: Counter[str] = Counter()
    samples: list[SimulationSample] = []
    matched_count = 0
    total_events = 0
    truncated = False

    for agent, events in await _iter_org_events(db, org_id, since):
        for event in events:
            total_events += 1
            if total_events > max_events:
                truncated = True
                break

            match = _match_event(compiled, target, event)
            if match is None:
                continue

            matched_count += 1
            by_agent[agent.name] += 1
            if event.timestamp:
                by_day[event.timestamp.date().isoformat()] += 1

            if len(samples) < sample_limit:
                samples.append(_sample_from(event, agent.name, match))

        if truncated:
            break

    match_rate = matched_count / total_events if total_events else 0.0
    return {
        "days_checked": days_back,
        "total_events_checked": total_events,
        "matched_count": matched_count,
        "match_rate": match_rate,
        "by_agent": dict(by_agent),
        "by_day": dict(by_day),
        "samples": samples,
        "truncated": truncated,
        "pattern_is_valid": True,
        "error": None,
    }


async def simulate_policy(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    policy: dict[str, Any],
    days_back: int = 30,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    max_events: int = MAX_SIMULATION_EVENTS,
) -> SimulationReport:
    """Simulate a (partial) policy against historical events.

    Calls `evaluate_policy()` per event so the simulation can never
    drift from runtime enforcement. The ``policy`` dict can be a
    delta — only fields present are evaluated. The matched_field on
    samples is reported as ``"prompt"`` (the policy is event-level,
    not field-level; the prompt is the user-facing text most worth
    showing in the sample list).
    """
    if not isinstance(policy, dict) or not policy:
        return _empty_report(
            days_back,
            error="Policy must be a non-empty object",
            pattern_valid=False,
        )

    # Validate any forbidden_patterns up front so we surface errors
    # before walking the event store.
    for pat in policy.get("forbidden_patterns") or []:
        try:
            validate_pattern(pat)
        except ValueError as e:
            return _empty_report(days_back, error=f"forbidden_patterns: {e}", pattern_valid=False)

    since = datetime.now(UTC) - timedelta(days=days_back)

    by_agent: Counter[str] = Counter()
    by_day: Counter[str] = Counter()
    samples: list[SimulationSample] = []
    matched_count = 0
    total_events = 0
    truncated = False

    for agent, events in await _iter_org_events(db, org_id, since):
        for event in events:
            total_events += 1
            if total_events > max_events:
                truncated = True
                break

            event_data = {
                "prompt": event.prompt,
                "response": event.response,
                "tool_calls": event.tool_calls,
                "token_count": event.token_count,
            }
            triggered, violations = evaluate_policy(policy, event_data)
            if not triggered:
                continue

            matched_count += 1
            by_agent[agent.name] += 1
            if event.timestamp:
                by_day[event.timestamp.date().isoformat()] += 1

            if len(samples) < sample_limit:
                samples.append(
                    {
                        "event_id": str(event.id),
                        "agent_name": agent.name,
                        "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                        "matched_field": "prompt",
                        "prompt_preview": _preview(event.prompt),
                        "response_preview": _preview(event.response),
                        "match_span": violations[0][:200],
                    }
                )

        if truncated:
            break

    match_rate = matched_count / total_events if total_events else 0.0
    return {
        "days_checked": days_back,
        "total_events_checked": total_events,
        "matched_count": matched_count,
        "match_rate": match_rate,
        "by_agent": dict(by_agent),
        "by_day": dict(by_day),
        "samples": samples,
        "truncated": truncated,
        "pattern_is_valid": True,
        "error": None,
    }
