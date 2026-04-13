import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.model_pricing import estimate_cost
from app.db.models import Agent, AgentEvent, AgentSession

log = structlog.get_logger()


async def ingest_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_name: str,
    prompt: str | None = None,
    response: str | None = None,
    model: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    latency_ms: int | None = None,
    token_count: int | None = None,
    session_id: str | None = None,
    timestamp: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentEvent:
    # Resolve agent by name within org (auto-create if not exists)
    result = await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.name == agent_name))
    agent = result.scalar_one_or_none()

    if agent is None:
        agent = Agent(org_id=org_id, name=agent_name)
        db.add(agent)
        await db.flush()
        log.info("agent.auto_created", agent_id=str(agent.id), name=agent_name)

    # Resolve or create session. session_id on the wire is a client
    # hint — the SDK sends whatever identifier makes sense to the
    # caller (a UUID, a request id, a chat thread id). We treat it as
    # a deterministic key: same agent + same client session_id ⇒
    # same AgentSession row, created on first sighting.
    db_session_id: uuid.UUID | None = None
    if session_id:
        # Try to interpret the client hint as an existing UUID that
        # already points to a session row for this agent. Otherwise
        # we create a fresh session. This is the only path that
        # ever creates AgentSession rows — without it the FK on
        # agent_events.session_id would fail the INSERT.
        try:
            parsed = uuid.UUID(session_id)
        except ValueError:
            parsed = None

        existing: AgentSession | None = None
        if parsed is not None:
            existing = await db.get(AgentSession, parsed)
            if existing is not None and existing.agent_id != agent.id:
                # Defence in depth: a client that sends a stolen
                # session_id from another agent shouldn't be able to
                # hijack its timeline.
                log.warning(
                    "event.session_id_cross_agent",
                    session_id=session_id,
                    claimed_agent=str(agent.id),
                    actual_agent=str(existing.agent_id),
                )
                existing = None

        if existing is None:
            new_session = AgentSession(
                id=parsed or uuid.uuid4(),
                agent_id=agent.id,
                metadata_={"client_session_id": session_id},
            )
            db.add(new_session)
            await db.flush()
            db_session_id = new_session.id
            log.info(
                "session.auto_created",
                session_id=str(db_session_id),
                agent_id=str(agent.id),
            )
        else:
            db_session_id = existing.id

    # Estimate USD cost from the model pricing registry. Use an 80/20
    # input/output token split when only a total count is available.
    input_tokens = int((token_count or 0) * 0.8)
    output_tokens = (token_count or 0) - input_tokens
    cost = estimate_cost(model, input_tokens, output_tokens)

    event = AgentEvent(
        agent_id=agent.id,
        session_id=db_session_id,
        prompt=prompt,
        response=response,
        model=model,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
        token_count=token_count,
        estimated_cost_usd=cost,
        timestamp=timestamp or datetime.now(UTC),
        metadata_=metadata,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    log.info(
        "event.ingested",
        event_id=str(event.id),
        agent_id=str(agent.id),
        model=model,
    )
    return event


async def list_events(
    db: AsyncSession,
    agent_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[AgentEvent], str | None]:
    query = (
        select(AgentEvent)
        .where(AgentEvent.agent_id == agent_id)
        .order_by(AgentEvent.timestamp.desc())
    )

    if cursor:
        cursor_id = uuid.UUID(cursor)
        # Can't use db.get() — AgentEvent is a hypertable with a
        # composite PK (id, timestamp). Query by id column instead.
        cursor_result = await db.execute(
            select(AgentEvent).where(AgentEvent.id == cursor_id)
        )
        cursor_event = cursor_result.scalar_one_or_none()
        if cursor_event:
            query = query.where(AgentEvent.timestamp < cursor_event.timestamp)

    query = query.limit(limit + 1)
    result = await db.execute(query)
    events = list(result.scalars().all())

    next_cursor = None
    if len(events) > limit:
        events = events[:limit]
        next_cursor = str(events[-1].id)

    return events, next_cursor


async def get_event(db: AsyncSession, event_id: uuid.UUID) -> AgentEvent:
    result = await db.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise NotFoundError("Event", str(event_id))
    return event
