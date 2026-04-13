"""Custom regex rule management API.

Rules live inside org.detector_config['custom_rules'] as a list of
dicts — no separate table. The API treats that list as the source
of truth and rewrites the JSONB on every mutation. Regex validity
is enforced on every write; runtime uses a secondary try/except as
defense in depth.

All mutation routes require admin+. The /test endpoint is viewer+
so read-only users can still preview what a rule would match.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, plan_service, policy_regression_service

log = structlog.get_logger()

router = APIRouter()

MAX_RULES_PER_ORG = 50


# ── Schemas ──────────────────────────────────────────────────────────


class CustomRuleBase(ParrySchema):
    name: str
    pattern: str
    target: Literal["prompt", "response", "both"] = "both"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    enabled: bool = True


class CustomRuleCreate(CustomRuleBase):
    pass


class CustomRuleUpdate(ParrySchema):
    name: str | None = None
    pattern: str | None = None
    target: Literal["prompt", "response", "both"] | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    enabled: bool | None = None


class CustomRuleResponse(CustomRuleBase):
    id: str
    created_at: str


class TestRuleRequest(ParrySchema):
    pattern: str
    sample: str


class TestRuleResponse(ParrySchema):
    matched: bool
    error: str | None = None
    match: str | None = None


class SimulateRuleRequest(ParrySchema):
    pattern: str
    target: Literal["prompt", "response", "both"] = "both"
    days_back: int = 30
    sample_limit: int = 10


class SimulateReportResponse(ParrySchema):
    days_checked: int
    total_events_checked: int
    matched_count: int
    match_rate: float
    by_agent: dict[str, int]
    by_day: dict[str, int]
    samples: list[dict[str, Any]]
    truncated: bool
    pattern_is_valid: bool
    error: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _validate_pattern(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regex: {e}",
        ) from e


def _load_rules(org: Org) -> list[dict[str, Any]]:
    cfg = org.detector_config or {}
    rules = cfg.get("custom_rules") or []
    return list(rules)


def _save_rules(org: Org, rules: list[dict[str, Any]]) -> None:
    cfg = dict(org.detector_config or {})
    cfg["custom_rules"] = rules
    org.detector_config = cfg


# ── Routes ───────────────────────────────────────────────────────────


@router.get("", response_model=list[CustomRuleResponse])
async def list_custom_rules(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
) -> list[CustomRuleResponse]:
    org, _ = org_actor
    return [CustomRuleResponse(**r) for r in _load_rules(org)]


@router.post("", response_model=CustomRuleResponse, status_code=201)
async def create_custom_rule(
    body: CustomRuleCreate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CustomRuleResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "custom_rules")
    _validate_pattern(body.pattern)

    rules = _load_rules(org)
    if len(rules) >= MAX_RULES_PER_ORG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rule limit reached ({MAX_RULES_PER_ORG}). Delete unused rules first.",
        )

    new_rule = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "pattern": body.pattern,
        "target": body.target,
        "severity": body.severity,
        "enabled": body.enabled,
        "created_at": datetime.now(UTC).isoformat(),
    }
    rules.append(new_rule)
    _save_rules(org, rules)
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="custom_rule.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="custom_rule",
        resource_id=str(new_rule["id"]),
        details={"name": new_rule["name"], "target": new_rule["target"]},
    )
    await db.commit()
    log.info("custom_rule.created", org_id=str(org.id), rule_id=new_rule["id"])
    return CustomRuleResponse(**new_rule)


@router.patch("/{rule_id}", response_model=CustomRuleResponse)
async def update_custom_rule(
    rule_id: str,
    body: CustomRuleUpdate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CustomRuleResponse:
    org, actor = org_actor
    rules = _load_rules(org)
    target = next((r for r in rules if r.get("id") == rule_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.pattern is not None:
        _validate_pattern(body.pattern)

    before = dict(target)
    updates = body.model_dump(exclude_unset=True)
    target.update(updates)
    _save_rules(org, rules)
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="custom_rule.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="custom_rule",
        resource_id=rule_id,
        details={"before": before, "after": dict(target)},
    )
    await db.commit()
    return CustomRuleResponse(**target)


@router.delete("/{rule_id}", status_code=204)
async def delete_custom_rule(
    rule_id: str,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    rules = _load_rules(org)
    remaining = [r for r in rules if r.get("id") != rule_id]
    if len(remaining) == len(rules):
        raise HTTPException(status_code=404, detail="Rule not found")

    _save_rules(org, remaining)
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="custom_rule.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="custom_rule",
        resource_id=rule_id,
    )
    await db.commit()


@router.post("/test", response_model=TestRuleResponse)
async def test_custom_rule(
    body: TestRuleRequest,
    _: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
) -> TestRuleResponse:
    """Test a regex pattern against sample text. No persistence — this
    is the UI's live preview endpoint so admins can verify regex before
    saving. Regex errors return error string instead of 400 so the UI
    can show them inline in the pattern field."""
    try:
        pattern = re.compile(body.pattern, re.I)
    except re.error as e:
        return TestRuleResponse(matched=False, error=str(e))

    m = pattern.search(body.sample)
    return TestRuleResponse(
        matched=m is not None,
        match=m.group(0) if m else None,
    )


@router.post("/simulate", response_model=SimulateReportResponse)
async def simulate_custom_rule(
    body: SimulateRuleRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SimulateReportResponse:
    """Run a candidate regex rule against the org's recent events.

    Read-only — no Detection rows written. Returns aggregate match
    stats + a small sample list so the dashboard can preview the
    blast radius before the admin saves the rule. Audit-logged with
    a hash of the pattern (not the pattern itself) to keep the audit
    trail compact and avoid leaking customer payloads.
    """
    org, actor = org_actor
    plan_service.require_feature(org, "custom_rules")

    report = await policy_regression_service.simulate_custom_rule(
        db,
        org.id,
        pattern=body.pattern,
        target=body.target,
        days_back=max(1, min(body.days_back, 90)),
        sample_limit=max(1, min(body.sample_limit, 50)),
    )

    pattern_hash = hashlib.sha256(body.pattern.encode("utf-8")).hexdigest()[:16]
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="custom_rule.simulated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="custom_rule",
        resource_id=pattern_hash,
        details={
            "pattern_hash": pattern_hash,
            "target": body.target,
            "days_back": body.days_back,
            "matched_count": report["matched_count"],
            "total_events_checked": report["total_events_checked"],
            "truncated": report["truncated"],
        },
    )
    await db.commit()
    return SimulateReportResponse(**report)
