"""Public badge endpoint — no auth required.

Serves an SVG badge showing the agent's current security grade.
The agent must have badge_public=True to be visible.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent
from app.db.session import get_db
from app.services.badge_service import generate_badge_svg, generate_unknown_badge_svg
from app.services.health_score_service import get_or_compute_health

log = structlog.get_logger()

router = APIRouter()

# Cache badges for 5 minutes — scores update hourly via Celery so
# this is generous without ever being stale for long.
_CACHE_CONTROL = "public, max-age=300, s-maxage=300"
_SVG_MEDIA = "image/svg+xml"


@router.get("/{agent_id}.svg")
async def get_badge(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Response:
    """Return an SVG badge for the agent's security score."""
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent or not agent.badge_public:
        svg = generate_unknown_badge_svg()
        return Response(
            content=svg,
            media_type=_SVG_MEDIA,
            headers={"Cache-Control": _CACHE_CONTROL},
        )

    try:
        health = await get_or_compute_health(db, agent_id)
        grade = health.get("grade", "?")
        score = health.get("score", 0)
    except Exception:
        log.debug("badge.health_score_failed", agent_id=str(agent_id), exc_info=True)
        grade, score = "?", 0

    svg = generate_badge_svg(grade, score)
    return Response(
        content=svg,
        media_type=_SVG_MEDIA,
        headers={"Cache-Control": _CACHE_CONTROL},
    )
