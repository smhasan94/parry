"""E2E: Normal events build baseline -> anomalous event triggers anomaly detector -> incident."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, Incident
from app.services.baseline_service import MIN_EVENTS
from app.services.detection_service import run_and_persist_detections


@pytest.mark.asyncio
async def test_anomaly_detected_after_baseline(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """Normal events establish baseline, then an anomalous event triggers the anomaly detector."""
    # 1. Ingest MIN_EVENTS normal events to build baseline
    for i in range(MIN_EVENTS):
        resp = await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": f"Normal question {i}",
                "response": f"Normal answer {i}",
                "model": "gpt-4o",
                "latency_ms": 120,
                "token_count": 30,
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )
        assert resp.status_code == 202

    # Run detection on last normal event to trigger baseline generation
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.agent_id == seeded_db["agent"].id)
        .order_by(AgentEvent.timestamp.desc())
        .limit(1)
    )
    last_normal = result.scalar_one()
    await run_and_persist_detections(db, last_normal)
    await db.commit()

    # Verify baseline was set
    await db.refresh(seeded_db["agent"])
    assert seeded_db["agent"].baseline is not None

    # 2. Ingest an anomalous event — wildly different metrics + unknown model
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Anomalous request",
            "response": "x" * 5000,
            "model": "unknown-model-xyz",
            "latency_ms": 15000,
            "token_count": 5000,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
    anomaly_event_id = resp.json()["event_id"]

    # 3. Run detection on the anomalous event
    result = await db.execute(select(AgentEvent).where(AgentEvent.id == anomaly_event_id))
    anomaly_event = result.scalar_one()
    detections = await run_and_persist_detections(db, anomaly_event)
    await db.commit()

    # 4. Anomaly detector should have triggered
    triggered = [d for d in detections if d.triggered]
    anomaly_detections = [d for d in triggered if d.detector == "anomaly"]
    assert len(anomaly_detections) >= 1

    # Check the anomaly details mention specific drift
    details = anomaly_detections[0].details
    assert details is not None
    anomalies = details.get("anomalies", [])
    assert len(anomalies) >= 2  # token + latency + model

    # 5. Incident should have been created
    result = await db.execute(select(Incident).where(Incident.org_id == seeded_db["org"].id))
    incidents = list(result.scalars().all())
    assert len(incidents) >= 1
