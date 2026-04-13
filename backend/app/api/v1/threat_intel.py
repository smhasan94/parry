"""Cross-org threat intelligence feed routes."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, plan_service, threat_intel_service

log = structlog.get_logger()
router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────


class IndicatorResponse(ParrySchema):
    id: uuid.UUID
    pattern_hash: str
    detector_source: str
    category: str
    severity: str
    confidence_avg: float
    sighting_count: int
    org_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    promoted_at: datetime | None
    score: float
    sample_reason: str | None


class FeedStatsResponse(ParrySchema):
    total_indicators: int
    active_indicators: int
    by_category: dict[str, int]


class SharingSettingsRequest(ParrySchema):
    threat_intel_sharing: bool


class SharingSettingsResponse(ParrySchema):
    threat_intel_sharing: bool


# ── Routes ──────────────────────────────────────────────────────


@router.get(
    "/feed",
    response_model=list[IndicatorResponse],
)
async def list_feed(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[IndicatorResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "threat_intelligence")
    indicators = await threat_intel_service.get_active_feed(db)
    return [IndicatorResponse.model_validate(i) for i in indicators]


@router.get(
    "/feed/{indicator_id}",
    response_model=IndicatorResponse,
)
async def get_indicator(
    indicator_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> IndicatorResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "threat_intelligence")
    indicator = await threat_intel_service.get_indicator(db, indicator_id)
    if indicator is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Indicator not found")
    return IndicatorResponse.model_validate(indicator)


@router.get(
    "/stats",
    response_model=FeedStatsResponse,
)
async def feed_stats(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> FeedStatsResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "threat_intelligence")
    stats = await threat_intel_service.get_feed_stats(db)
    return FeedStatsResponse(**stats)


@router.patch(
    "/settings",
    response_model=SharingSettingsResponse,
)
async def update_sharing_settings(
    body: SharingSettingsRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> SharingSettingsResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "threat_intelligence")

    before = org.threat_intel_sharing
    org.threat_intel_sharing = body.threat_intel_sharing

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="threat_intel.sharing_updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="org",
        resource_id=str(org.id),
        details={"before": before, "after": body.threat_intel_sharing},
    )
    await db.commit()

    return SharingSettingsResponse(threat_intel_sharing=org.threat_intel_sharing)
