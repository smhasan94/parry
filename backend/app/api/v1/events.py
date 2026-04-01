import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_org, get_org_from_sdk_key
from app.db.models import Org
from app.db.session import get_db
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


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    event = await event_service.get_event(db, event_id)
    return EventResponse.model_validate(event)
