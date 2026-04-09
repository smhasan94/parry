"""Celery task: execute a queued red team run.

Sandbox mode replays the bundled corpus through the same
`DetectionPipeline` real events use, **without persisting** any
`AgentEvent` or `Detection` rows. The run's outcome lives in
`red_team_runs` + `red_team_results`.

Live mode is reserved for a follow-up — see plan-13-17, plan 14
"Task 13 — Live mode".
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="run_red_team",
    soft_time_limit=600,
    time_limit=660,
)
def run_red_team(run_id: str) -> dict:
    return asyncio.run(_run_red_team(run_id))


async def _run_red_team(run_id: str) -> dict:
    from app.db.models import Agent, Org, RedTeamResult, RedTeamRun
    from app.db.session import make_task_session_factory
    from app.services.red_team_service import score_results

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    try:
        async with factory() as db:
            run = (
                await db.execute(
                    select(RedTeamRun).where(RedTeamRun.id == uuid.UUID(run_id))
                )
            ).scalar_one()
            run.status = "running"
            await db.commit()

            try:
                agent = await db.get(Agent, run.agent_id)
                org = await db.get(Org, run.org_id)
                if agent is None or org is None:
                    raise RuntimeError("agent or org missing for red team run")

                if run.mode == "sandbox":
                    raw_results = await _run_sandbox(db, agent, org)
                else:
                    # Live mode is gated separately and not implemented
                    # in v1. Fail loudly so the API can surface a 501.
                    raise NotImplementedError("live mode is not yet supported")

                stats = score_results(raw_results)

                run.status = "completed"
                run.total_attacks = stats["total"]
                run.detected_count = stats["detected"]
                run.overall_score = stats["score"]
                run.grade = stats["grade"]
                run.category_scores = stats["by_category"]
                run.completed_at = datetime.now(UTC)

                for r in raw_results:
                    db.add(
                        RedTeamResult(
                            run_id=run.id,
                            attack_id=r["attack_id"],
                            attack_category=r["category"],
                            attack_severity=r["severity"],
                            detected=r["detected"],
                            detectors_fired=r["detectors_fired"],
                            max_confidence=r["max_confidence"],
                        )
                    )
                await db.commit()
                log.info(
                    "red_team.run_completed",
                    run_id=run_id,
                    score=stats["score"],
                    grade=stats["grade"],
                )
                return stats
            except Exception as e:  # noqa: BLE001 — top-level worker boundary
                log.error("red_team.run_failed", run_id=run_id, exc_info=True)
                run.status = "failed"
                run.error_message = str(e)[:500]
                run.completed_at = datetime.now(UTC)
                await db.commit()
                return {"error": str(e)}
    finally:
        await task_engine.dispose()


async def _run_sandbox(db: Any, agent: Any, org: Any) -> list[dict]:
    """Replay the corpus through `DetectionPipeline` for one agent.

    Builds synthetic ``event_data`` per attack — same shape as the
    real ingest path so the same detectors run with the same merged
    config + policy as production traffic. Importantly: no
    AgentEvent / Detection rows are written. The red team has its
    own storage.
    """
    from app.detection.pipeline import DetectionPipeline
    from app.detection.red_team_corpus import load_corpus
    from app.services.detection_service import _get_active_policies, _merge_policies
    from app.services.detector_config_service import merged_config

    corpus = load_corpus()
    detector_config = merged_config(org.detector_config)
    policies = await _get_active_policies(db, org.id)
    merged_policy = _merge_policies(policies)
    pipeline = DetectionPipeline()

    results: list[dict] = []
    for attack in corpus:
        event_data: dict[str, Any] = {
            "prompt": attack.get("prompt"),
            "response": attack.get("response") or "",
            "model": "sandbox",
            "tool_calls": attack.get("tool_calls") or [],
            "latency_ms": 0,
            "token_count": 0,
            "policy": merged_policy,
            "detector_config": detector_config,
            "baseline": agent.baseline or {},
        }

        detection_results = await pipeline.run(event_data)
        triggered = [r for r in detection_results if r.triggered]

        expected = set(attack.get("expected_detectors") or [])
        actual = {r.detector for r in triggered}
        # If the attack lists expected detectors, count it as caught
        # only when at least one of them fires. Otherwise, any trigger
        # counts. This rewards correctly-attributed detection over
        # accidental catches by an unrelated detector.
        detected = bool(expected & actual) if expected else len(triggered) > 0

        results.append(
            {
                "attack_id": attack["id"],
                "category": attack["category"],
                "severity": attack["severity_expected"],
                "detected": detected,
                "detectors_fired": list(actual),
                "max_confidence": max(
                    (r.confidence for r in triggered), default=0.0
                ),
            }
        )

    return results
