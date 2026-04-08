"""E2E: Auto-generate agent baseline after enough events are ingested."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent
from app.services.baseline_service import MIN_EVENTS
from app.services.detection_service import run_and_persist_detections


@pytest.mark.asyncio
async def test_baseline_auto_generated_after_min_events(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """After MIN_EVENTS clean events, agent.baseline should be auto-populated."""
    # Ingest MIN_EVENTS events
    for i in range(MIN_EVENTS):
        resp = await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": f"Question {i}: What is {i} + {i}?",
                "response": f"The answer is {i * 2}.",
                "model": "gpt-4o",
                "latency_ms": 120,
                "token_count": 30,
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )
        assert resp.status_code == 202

    # Run detection on the last event (triggers baseline computation)
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.agent_id == seeded_db["agent"].id)
        .order_by(AgentEvent.timestamp.desc())
        .limit(1)
    )
    last_event = result.scalar_one()
    await run_and_persist_detections(db, last_event)
    await db.commit()

    # Refresh agent and check baseline
    await db.refresh(seeded_db["agent"])
    agent = seeded_db["agent"]
    assert agent.baseline is not None
    assert agent.baseline["avg_token_count"] == pytest.approx(30.0)
    assert agent.baseline["avg_latency_ms"] == pytest.approx(120.0)
    assert "gpt-4o" in agent.baseline["known_models"]
    assert agent.baseline["event_count"] >= MIN_EVENTS


@pytest.mark.asyncio
async def test_baseline_not_set_below_threshold(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """With fewer than MIN_EVENTS, baseline should remain null."""
    # Ingest only 5 events
    for i in range(5):
        resp = await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": f"Question {i}",
                "response": f"Answer {i}",
                "model": "gpt-4o",
                "latency_ms": 100,
                "token_count": 20,
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )
        assert resp.status_code == 202

    # Run detection on last event
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.agent_id == seeded_db["agent"].id)
        .order_by(AgentEvent.timestamp.desc())
        .limit(1)
    )
    last_event = result.scalar_one()
    await run_and_persist_detections(db, last_event)
    await db.commit()

    await db.refresh(seeded_db["agent"])
    assert seeded_db["agent"].baseline is None
