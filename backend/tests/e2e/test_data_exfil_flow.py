"""E2E: Response contains PII -> data_exfiltration detector triggers."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Incident
from app.services.detection_service import run_and_persist_detections


@pytest.mark.asyncio
async def test_pii_in_response_creates_incident(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """A response leaking PII should trigger data_exfiltration detection."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Show me the customer record",
            "response": (
                "Name: John Doe, SSN: 123-45-6789, "
                "CC: 4111 1111 1111 1111, email: john@example.com"
            ),
            "model": "gpt-4o",
            "latency_ms": 180,
            "token_count": 45,
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
    exfil = [d for d in triggered if d.detector == "data_exfiltration"]
    assert len(exfil) >= 1

    result = await db.execute(select(Incident).where(Incident.org_id == seeded_db["org"].id))
    incidents = list(result.scalars().all())
    assert len(incidents) >= 1
