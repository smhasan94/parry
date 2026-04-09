"""Red Team API.

Customer-facing routes:

- `POST   /red-team/runs`            — start a sandbox run for an agent
- `GET    /red-team/runs`            — list runs (optionally per agent)
- `GET    /red-team/runs/{run_id}`   — full run detail incl. failures
- `GET    /red-team/attacks`         — corpus summary (counts by category)

The corpus prompts themselves are NEVER returned by the API. Shipping
them in JSON would hand adversaries a curated attack library.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Agent, Org, RedTeamRun
from app.db.session import get_db
from app.schemas.base import ParrySchema
from app.services import audit_service, plan_service, red_team_service

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class StartRunRequest(ParrySchema):
    agent_id: uuid.UUID
    mode: Literal["sandbox", "live"] = "sandbox"


class StartRunResponse(ParrySchema):
    run_id: str
    status: str


class RunSummary(ParrySchema):
    id: str
    agent_id: str
    mode: str
    status: str
    overall_score: int | None
    grade: str | None
    total_attacks: int | None
    detected_count: int | None
    started_at: datetime
    completed_at: datetime | None


class RunFailure(ParrySchema):
    attack_id: str
    category: str
    severity: str
    detectors_fired: list[str]


class RunDetail(RunSummary):
    by_category: dict[str, int] | None
    error_message: str | None
    failures: list[RunFailure]


class CorpusSummary(ParrySchema):
    total_attacks: int
    by_category: dict[str, int]


# ── Helpers ──────────────────────────────────────────────────────────


def _summary(run: RedTeamRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "agent_id": str(run.agent_id),
        "mode": run.mode,
        "status": run.status,
        "overall_score": run.overall_score,
        "grade": run.grade,
        "total_attacks": run.total_attacks,
        "detected_count": run.detected_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/runs", response_model=StartRunResponse, status_code=202)
async def start_run(
    body: StartRunRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> StartRunResponse:
    org, actor = org_actor

    plan_service.require_feature(org, "red_team")
    if body.mode == "live":
        plan_service.require_feature(org, "red_team_live")

    # Confirm the agent belongs to this org before kicking off any
    # background work.
    agent = await db.get(Agent, body.agent_id)
    if agent is None or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = await red_team_service.start_run(
        db,
        org_id=org.id,
        agent_id=body.agent_id,
        mode=body.mode,
        started_by=actor.label or actor.actor_id,
    )

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="red_team.run_started",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="red_team_run",
        resource_id=str(run.id),
        details={"agent_id": str(body.agent_id), "mode": body.mode},
    )
    await db.commit()

    # Enqueue the worker after commit so the row is visible by the
    # time the worker picks it up.
    from app.workers.red_team_task import run_red_team

    try:
        run_red_team.delay(str(run.id))
    except Exception as e:  # pragma: no cover — broker outage
        log.error("red_team.enqueue_failed", run_id=str(run.id), error=str(e))
        # Don't fail the API call — the run row will sit in queued
        # state and the next manual trigger / retry can pick it up.

    return StartRunResponse(run_id=str(run.id), status=run.status)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    agent_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[RunSummary]:
    org, _ = org_actor
    runs = await red_team_service.list_runs(
        db, org_id=org.id, agent_id=agent_id, limit=limit
    )
    return [RunSummary(**_summary(r)) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> RunDetail:
    org, _ = org_actor
    run = await red_team_service.get_run(db, org_id=org.id, run_id=run_id)
    failures = await red_team_service.list_results(
        db, run_id=run_id, only_undetected=True
    )
    return RunDetail(
        **_summary(run),
        by_category=run.category_scores,
        error_message=run.error_message,
        failures=[
            RunFailure(
                attack_id=f.attack_id,
                category=f.attack_category,
                severity=f.attack_severity,
                detectors_fired=f.detectors_fired or [],
            )
            for f in failures
        ],
    )


@router.get("/attacks", response_model=CorpusSummary)
async def list_attacks(
    _: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
) -> CorpusSummary:
    """Public-safe corpus view: just the categories and counts.

    The actual attack prompts are intentionally never serialized.
    """
    from app.detection.red_team_corpus import category_summary, load_corpus

    summary = category_summary()
    return CorpusSummary(
        total_attacks=len(load_corpus()),
        by_category=summary,
    )
