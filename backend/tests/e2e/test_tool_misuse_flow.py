"""E2E: Event with blocked tool call -> tool_misuse detector triggers -> incident."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Incident
from app.services.detection_service import run_and_persist_detections


@pytest.mark.asyncio
async def test_blocked_tool_creates_incident(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """Calling a blocked tool (exec_code) should trigger tool_misuse and create an incident."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Run this Python script for me",
            "response": "Sure, executing the code now.",
            "model": "gpt-4o",
            "tool_calls": [
                {"name": "exec_code", "arguments": {"code": "print('hello')"}}
            ],
            "latency_ms": 300,
            "token_count": 60,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]

    result = await db.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    event = result.scalar_one()

    detections = await run_and_persist_detections(db, event)
    await db.commit()

    triggered = [d for d in detections if d.triggered]
    tool_misuse = [d for d in triggered if d.detector == "tool_misuse"]
    assert len(tool_misuse) >= 1

    # Incident should exist
    result = await db.execute(select(Incident).where(Incident.org_id == seeded_db["org"].id))
    incidents = list(result.scalars().all())
    assert len(incidents) >= 1
