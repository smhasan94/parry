"""Detector tuning API — read and update per-org detector thresholds."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service
from app.services.detector_config_service import (
    DEFAULT_DETECTOR_CONFIG,
    DETECTOR_NAMES,
    merged_config,
    validate_config,
)

log = structlog.get_logger()

router = APIRouter()


class DetectorEntry(ParrySchema):
    trigger_threshold: float
    enabled: bool
    is_default: bool  # True if no org override
    sigma_threshold: float | None = None  # anomaly detector only


class DetectorConfigResponse(ParrySchema):
    detectors: dict[str, DetectorEntry]


def _build_response(org_config: dict | None) -> DetectorConfigResponse:
    overrides = org_config or {}
    merged = merged_config(org_config)
    detectors = {}
    for name in DETECTOR_NAMES:
        merged_entry = merged[name]
        detectors[name] = DetectorEntry(
            trigger_threshold=merged_entry["trigger_threshold"],
            enabled=merged_entry["enabled"],
            is_default=name not in overrides,
            sigma_threshold=merged_entry.get("sigma_threshold"),
        )
    return DetectorConfigResponse(detectors=detectors)


@router.get(
    "",
    response_model=DetectorConfigResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_detector_config(
    org: Org = Depends(get_current_org),
) -> DetectorConfigResponse:
    """Return the effective detector config (defaults merged with org overrides)."""
    return _build_response(org.detector_config)


@router.get(
    "/defaults",
    response_model=DetectorConfigResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_default_detector_config() -> DetectorConfigResponse:
    """Return Parry's built-in defaults — useful for 'reset to default' UI."""
    detectors = {
        name: DetectorEntry(
            trigger_threshold=cfg["trigger_threshold"],
            enabled=cfg["enabled"],
            is_default=True,
            sigma_threshold=cfg.get("sigma_threshold"),
        )
        for name, cfg in DEFAULT_DETECTOR_CONFIG.items()
    }
    return DetectorConfigResponse(detectors=detectors)


@router.put(
    "",
    response_model=DetectorConfigResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_detector_config(
    body: dict[str, Any],
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> DetectorConfigResponse:
    """Replace the org's detector config overrides.

    Body shape: {"prompt_injection": {"trigger_threshold": 0.5, "enabled": true}, ...}
    Only provided fields override defaults; omitted detectors use defaults.
    """
    try:
        cleaned = validate_config(body)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    org, actor = org_actor
    before = dict(org.detector_config or {})
    org.detector_config = cleaned
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="detector_config.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="detector_config",
        details={"before": before, "after": cleaned},
    )
    await db.commit()
    log.info("detector_config.updated", org_id=str(org.id))
    return _build_response(cleaned)


@router.delete(
    "",
    status_code=204,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def reset_detector_config(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear all org overrides — every detector returns to its default."""
    org, actor = org_actor
    snapshot = dict(org.detector_config or {})
    org.detector_config = None
    await db.flush()
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="detector_config.reset",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="detector_config",
        details={"removed": snapshot},
    )
    await db.commit()
