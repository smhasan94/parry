"""E2E: Ingest a clean event -> detection runs -> no incident created."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Incident
from app.services.detection_service import run_and_persist_detections


@pytest.mark.asyncio
async def test_clean_event_no_incident(client: AsyncClient, seeded_db: dict, db: AsyncSession):
    """A benign prompt should be ingested, detected clean, and produce zero incidents."""
    # 1. Ingest via API
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "What is the capital of France?",
            "response": "The capital of France is Paris.",
            "model": "gpt-4o",
            "latency_ms": 120,
            "token_count": 30,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]

    # 2. Verify event persisted
    result = await db.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    event = result.scalar_one()
    assert event.prompt == "What is the capital of France?"

    # 3. Run detection pipeline synchronously (bypass Celery)
    detections = await run_and_persist_detections(db, event)
    await db.commit()

    # 4. No detections should trigger
    triggered = [d for d in detections if d.triggered]
    assert len(triggered) == 0

    # 5. No incident created
    result = await db.execute(select(Incident))
    incidents = list(result.scalars().all())
    assert len(incidents) == 0

    # 6. Verify event retrievable via list API
    resp = await client.get(
        f"/api/v1/events?agent_id={event.agent_id}",
        headers={"Authorization": f"Bearer {seeded_db['api_key_raw']}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["events"]) >= 1
