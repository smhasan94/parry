"""Periodic task to refresh stale agent baselines.

A baseline is considered stale when:
- It was computed more than STALE_AFTER_DAYS ago, OR
- The agent's current event count is more than GROWTH_FACTOR× the count at
  the time the baseline was computed.

The task scans all agents that have a baseline, recomputes any stale ones,
and writes a system-actor audit log entry for each refresh.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select

from app.workers.celery_app import celery_app

log = structlog.get_logger()

STALE_AFTER_DAYS = 7
GROWTH_FACTOR = 1.5


@celery_app.task(  # type: ignore[untyped-decorator]
    name="refresh_stale_baselines",
    soft_time_limit=300,
    time_limit=360,
)
def refresh_stale_baselines() -> dict[str, int]:
    """Periodically recompute baselines that are stale."""
    return asyncio.run(_refresh_stale_baselines())


async def _refresh_stale_baselines() -> dict[str, int]:
    from app.db.models import Agent, AgentEvent
    from app.db.session import make_task_session_factory
    from app.services import audit_service
    from app.services.baseline_service import compute_baseline

    refreshed = 0
    skipped = 0
    errored = 0
    cutoff = datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)

    # Disposable per-task engine — see make_task_session_factory
    # docstring for the "Task attached to a different loop" story.
    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            agents = (
                (await db.execute(select(Agent).where(Agent.baseline.is_not(None))))
                .scalars()
                .all()
            )

            for agent in agents:
                try:
                    baseline = agent.baseline or {}
                    computed_at_str = baseline.get("computed_at")
                    old_event_count = int(baseline.get("event_count") or 0)

                    # Compute current event count
                    current_count = (
                        await db.execute(
                            select(func.count())
                            .select_from(AgentEvent)
                            .where(AgentEvent.agent_id == agent.id)
                        )
                    ).scalar_one()

                    is_age_stale = False
                    if computed_at_str:
                        try:
                            computed_at = datetime.fromisoformat(computed_at_str)
                            if computed_at < cutoff:
                                is_age_stale = True
                        except (ValueError, TypeError):
                            is_age_stale = True

                    is_growth_stale = (
                        old_event_count > 0
                        and current_count > old_event_count * GROWTH_FACTOR
                    )

                    if not (is_age_stale or is_growth_stale):
                        skipped += 1
                        continue

                    before = dict(baseline)
                    new_baseline = await compute_baseline(db, agent.id)
                    if new_baseline is None:
                        skipped += 1
                        continue

                    agent.baseline = new_baseline
                    await db.flush()

                    await audit_service.log_action(
                        db,
                        org_id=agent.org_id,
                        action="baseline.recomputed",
                        actor_type="system",
                        actor_label="baseline-refresh-task",
                        resource_type="agent",
                        resource_id=str(agent.id),
                        details={
                            "before": before,
                            "after": new_baseline,
                            "reason": "stale_age" if is_age_stale else "stale_growth",
                        },
                    )
                    await db.commit()
                    refreshed += 1
                    log.info(
                        "baseline.refreshed",
                        agent_id=str(agent.id),
                        reason="stale_age" if is_age_stale else "stale_growth",
                        old_event_count=old_event_count,
                        new_event_count=current_count,
                    )
                except Exception:
                    errored += 1
                    await db.rollback()
                    log.error(
                        "baseline.refresh_failed",
                        agent_id=str(agent.id),
                        exc_info=True,
                    )

        log.info(
            "baseline.refresh_run_complete",
            refreshed=refreshed,
            skipped=skipped,
            errored=errored,
        )
        return {"refreshed": refreshed, "skipped": skipped, "errored": errored}
    finally:
        await task_engine.dispose()
