"""Periodic task: refresh the Redis health-score cache for every agent.

Runs hourly via Celery Beat. Computes live scores for all agents in
every org and writes them into the ``health:{agent_id}`` cache so the
HTTP GET handlers serve from a warm cache almost all the time. Falls
back to per-request computation on cache miss (see
``health_score_service.get_or_compute_health``).
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="refresh_health_scores",
    soft_time_limit=300,
    time_limit=360,
)
def refresh_health_scores() -> dict[str, int]:
    """Recompute and cache health scores for every agent."""
    return asyncio.run(_refresh_health_scores())


async def _refresh_health_scores() -> dict[str, int]:
    from app.db.models import Agent
    from app.db.session import async_session_factory
    from app.services.health_score_service import (
        compute_health_score,
        set_cached_health,
    )

    refreshed = 0
    errored = 0

    async with async_session_factory() as db:
        agents = (await db.execute(select(Agent))).scalars().all()

        for agent in agents:
            try:
                payload = await compute_health_score(db, agent.id)
                set_cached_health(agent.id, payload)
                refreshed += 1
            except Exception:
                errored += 1
                log.error(
                    "health_score.refresh_failed",
                    agent_id=str(agent.id),
                    exc_info=True,
                )

    log.info(
        "health_score.refresh_run_complete",
        refreshed=refreshed,
        errored=errored,
    )
    return {"refreshed": refreshed, "errored": errored}
