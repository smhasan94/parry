"""SDK integration health service.

Surfaces per-agent SDK integration status: last event timestamp,
SDK version, wrapper type, event rate, and staleness detection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def compute_sdk_health(
    agents: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute SDK health for a list of agents.

    Each agent dict should include:
        - id, name
        - last_event_at: ISO timestamp or None
        - sdk_version: str or None
        - wrapper_type: str or None (e.g. "openai", "anthropic", "langchain")
        - event_count_24h: int
    """
    now = now or datetime.now(UTC)
    stale_threshold = now - timedelta(hours=3)

    healthy = 0
    stale = 0
    silent = 0
    agents_health = []

    for a in agents:
        last_event = a.get("last_event_at")
        if last_event is None:
            status = "silent"
            silent += 1
        elif isinstance(last_event, str):
            try:
                ts = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
            except ValueError:
                status = "unknown"
                silent += 1
                agents_health.append({**a, "status": status})
                continue

            if ts >= stale_threshold:
                status = "healthy"
                healthy += 1
            else:
                status = "stale"
                stale += 1
        else:
            ts = last_event
            if ts >= stale_threshold:
                status = "healthy"
                healthy += 1
            else:
                status = "stale"
                stale += 1

        agents_health.append({**a, "status": status})

    # Sort: silent first, then stale, then healthy
    status_rank = {"silent": 0, "stale": 1, "unknown": 1, "healthy": 2}
    agents_health.sort(key=lambda a: status_rank.get(a.get("status", ""), 99))

    return {
        "total": len(agents),
        "healthy": healthy,
        "stale": stale,
        "silent": silent,
        "agents": agents_health,
    }
