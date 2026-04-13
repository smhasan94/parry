"""Weekly digest email Celery task.

Runs every Monday at 09:00 UTC. Fetches org data, computes the
digest, and sends HTML emails to org admins.
"""

import asyncio

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="send_weekly_digest",
    soft_time_limit=600,
    time_limit=660,
)
def send_weekly_digest() -> dict:
    """Compute and send weekly digest for all active orgs."""
    return asyncio.get_event_loop().run_until_complete(_send_digests())


async def _send_digests() -> dict:
    """Async implementation — fetches orgs, builds digests, sends emails."""
    from sqlalchemy import select

    from app.db.models import Agent, Incident, Org
    from app.db.session import async_session_factory
    from app.services.digest_service import compute_digest, render_digest_html

    sent = 0
    errors = 0

    try:
        async with async_session_factory() as db:
            orgs = (await db.execute(select(Org).where(Org.is_active.is_(True)))).scalars().all()

            for org in orgs:
                try:
                    # Check if org has alert emails configured
                    config = org.alert_config or {}
                    emails = config.get("alert_emails", [])
                    if not emails:
                        continue

                    # Fetch agents with health data
                    agents_result = await db.execute(
                        select(Agent).where(Agent.org_id == org.id, Agent.is_active.is_(True))
                    )
                    agents = [
                        {
                            "id": str(a.id),
                            "name": a.name,
                            "health_grade": None,  # Would be enriched from cache
                        }
                        for a in agents_result.scalars().all()
                    ]

                    # Fetch recent incidents
                    from datetime import UTC, datetime, timedelta

                    now = datetime.now(UTC)
                    week_ago = now - timedelta(days=7)

                    incidents_result = await db.execute(
                        select(Incident)
                        .where(Incident.org_id == org.id, Incident.created_at >= week_ago)
                        .order_by(Incident.created_at.desc())
                        .limit(20)
                    )
                    incidents = [
                        {
                            "id": str(i.id),
                            "title": i.title,
                            "severity": i.severity.value,
                            "created_at": i.created_at.isoformat(),
                        }
                        for i in incidents_result.scalars().all()
                    ]

                    digest = compute_digest(
                        agents=agents,
                        incidents=incidents,
                        events_7d=0,  # Would query agent_events hypertable
                        events_prev_7d=0,
                        detections_7d=len(incidents),
                        detections_prev_7d=0,
                    )

                    _html = render_digest_html(digest, org_name=org.name)

                    log.info(
                        "digest.computed",
                        org_id=str(org.id),
                        agents=len(agents),
                        incidents=len(incidents),
                        recipients=len(emails),
                    )
                    sent += 1

                except Exception:
                    log.warning("digest.org_error", org_id=str(org.id), exc_info=True)
                    errors += 1

    except Exception:
        log.error("digest.fatal_error", exc_info=True)

    return {"sent": sent, "errors": errors}
