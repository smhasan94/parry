import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.dependencies import get_current_org, get_org_from_sdk_key
from app.db.models import AgentEvent, Org
from app.db.session import async_session_factory, get_db
from app.schemas.event import EventIngest, EventListResponse, EventResponse
from app.services import event_service

log = structlog.get_logger()

router = APIRouter()


@router.post("/ingest", status_code=202)
async def ingest_event(
    body: EventIngest,
    org: Org = Depends(get_org_from_sdk_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Receive an event from the SDK. Authenticated via X-Parry-Secret API key."""
    event = await event_service.ingest_event(
        db,
        org_id=org.id,
        agent_name=body.agent_id,
        prompt=body.prompt,
        response=body.response,
        model=body.model,
        tool_calls=body.tool_calls,
        latency_ms=body.latency_ms,
        token_count=body.token_count,
        session_id=body.session_id,
        timestamp=body.timestamp,
        metadata=body.metadata,
    )
    await db.commit()

    # Dispatch detection pipeline async via Celery
    try:
        from app.workers.detection_task import run_detection_pipeline

        run_detection_pipeline.delay(str(event.id))
    except Exception:
        log.warning("detection.dispatch_failed", event_id=str(event.id), exc_info=True)

    return {"event_id": str(event.id), "status": "accepted"}


@router.get("", response_model=EventListResponse)
async def list_events(
    agent_id: uuid.UUID = Query(...),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> EventListResponse:
    events, next_cursor = await event_service.list_events(db, agent_id, cursor, limit)
    return EventListResponse(
        events=[EventResponse.model_validate(e) for e in events],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/stream")
async def stream_events(
    agent_id: uuid.UUID = Query(...),
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """SSE endpoint for real-time event streaming. Scoped to org's agents."""
    from app.db.models import Agent

    # Verify agent belongs to this org
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org.id))
    if result.scalar_one_or_none() is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        last_seen: uuid.UUID | None = None
        while True:
            async with async_session_factory() as session:
                query = (
                    select(AgentEvent)
                    .where(AgentEvent.agent_id == agent_id)
                    .order_by(AgentEvent.timestamp.desc())
                    .limit(1)
                )
                result = await session.execute(query)
                event = result.scalar_one_or_none()

                if event and event.id != last_seen:
                    last_seen = event.id
                    data = json.dumps(EventResponse.model_validate(event).model_dump(mode="json"))
                    yield {"data": data}

            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    event = await event_service.get_event(db, event_id)
    return EventResponse.model_validate(event)
