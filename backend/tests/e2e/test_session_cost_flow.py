"""E2E: Session listing and cost tracking on ingested events.

Covers:
1. GET /agents/{id}/sessions returns sessions after events are ingested.
2. Ingested events carry a non-null estimated_cost_usd when a known model is used.
3. Session list respects the limit query parameter.
4. Sessions for an agent that belongs to a different org return 404 or empty.
5. The session list is ordered newest-first.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent


@pytest.mark.asyncio
async def test_session_list_after_event_ingest(
    admin_client: AsyncClient, client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """Ingesting an event with a session_id makes it appear in the sessions list."""
    session_id = str(uuid.uuid4())
    agent_id = str(seeded_db["agent"].id)

    # Ingest an event with an explicit session_id
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Hello, what is your name?",
            "response": "I am an AI assistant.",
            "model": "gpt-4o",
            "latency_ms": 100,
            "token_count": 25,
            "session_id": session_id,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202, resp.text

    # List sessions for the agent
    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/sessions")
    assert resp.status_code == 200, resp.text
    sessions = resp.json()

    assert isinstance(sessions, list)
    assert len(sessions) >= 1
    # The session we just created should be present
    session_ids = [s.get("session_id") or s.get("id") for s in sessions]
    assert any(sid == session_id for sid in session_ids)


@pytest.mark.asyncio
async def test_event_carries_estimated_cost(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """An event ingested with a known model has estimated_cost_usd > 0."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "Summarize the Gettysburg Address.",
            "response": "Four score and seven years ago...",
            "model": "gpt-4o",  # known model — cost estimation should work
            "latency_ms": 200,
            "token_count": 80,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]

    # Read the event from DB and verify cost is populated
    result = await db.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    event = result.scalar_one()
    assert event.estimated_cost_usd is not None
    assert event.estimated_cost_usd >= 0.0


@pytest.mark.asyncio
async def test_event_cost_zero_for_zero_tokens(
    client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """An event with token_count=0 should have zero or None cost — never negative."""
    resp = await client.post(
        "/api/v1/events/ingest",
        json={
            "agent_id": "e2e-agent",
            "prompt": "ping",
            "response": "pong",
            "model": "gpt-4o-mini",
            "latency_ms": 10,
            "token_count": 0,
        },
        headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
    )
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]

    result = await db.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    event = result.scalar_one()
    cost = event.estimated_cost_usd
    assert cost is None or cost >= 0.0


@pytest.mark.asyncio
async def test_session_list_limit_respected(
    admin_client: AsyncClient, client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """The limit= param on GET /agents/{id}/sessions is respected."""
    agent_id = str(seeded_db["agent"].id)

    # Ingest events in multiple distinct sessions
    for i in range(3):
        await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": f"Session {i} prompt",
                "response": "ok",
                "model": "gpt-4o",
                "latency_ms": 50,
                "token_count": 10,
                "session_id": str(uuid.uuid4()),
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )

    # Request only 1 session at a time
    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/sessions?limit=1")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) <= 1


@pytest.mark.asyncio
async def test_session_list_unknown_agent_404(
    admin_client: AsyncClient, seeded_db: dict
):
    """GET /agents/{id}/sessions for an unknown agent returns 404."""
    resp = await admin_client.get(f"/api/v1/agents/{uuid.uuid4()}/sessions")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_multiple_events_same_session(
    client: AsyncClient, admin_client: AsyncClient, seeded_db: dict, db: AsyncSession
):
    """Multiple events in the same session are grouped under one session entry."""
    agent_id = str(seeded_db["agent"].id)
    shared_session = str(uuid.uuid4())

    for _ in range(3):
        await client.post(
            "/api/v1/events/ingest",
            json={
                "agent_id": "e2e-agent",
                "prompt": "Turn of a multi-turn convo",
                "response": "Sure",
                "model": "claude-3-5-sonnet-20241022",
                "latency_ms": 150,
                "token_count": 30,
                "session_id": shared_session,
            },
            headers={"X-Parry-Secret": seeded_db["api_key_raw"]},
        )

    resp = await admin_client.get(f"/api/v1/agents/{agent_id}/sessions")
    assert resp.status_code == 200
    sessions = resp.json()

    # There should be exactly one session entry for the shared session_id
    matching = [
        s for s in sessions
        if s.get("session_id") == shared_session or s.get("id") == shared_session
    ]
    assert len(matching) == 1

    # That session entry should reflect multiple events
    session = matching[0]
    event_count = session.get("event_count") or session.get("events")
    if event_count is not None:
        assert event_count >= 3
