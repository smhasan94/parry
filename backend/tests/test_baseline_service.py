"""Tests for baseline_service.compute_baseline()."""
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Agent, AgentEvent, Org
from app.services.baseline_service import MIN_EVENTS, compute_baseline

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://parry:parry@localhost:5434/parry_test",
)


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from sqlalchemy import text

    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_agent(db: AsyncSession) -> Agent:
    org = Org(name="Baseline Test Org", clerk_org_id=f"clerk_{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    agent = Agent(org_id=org.id, name="baseline-agent", is_active=True)
    db.add(agent)
    await db.flush()
    return agent


async def _add_events(
    db: AsyncSession,
    agent: Agent,
    count: int,
    token_count: int = 30,
    latency_ms: int = 120,
    model: str = "gpt-4o",
    tool_calls: list | None = None,
) -> None:
    for _ in range(count):
        db.add(
            AgentEvent(
                agent_id=agent.id,
                timestamp=datetime.now(timezone.utc),
                prompt="test prompt",
                response="test response",
                model=model,
                token_count=token_count,
                latency_ms=latency_ms,
                tool_calls=tool_calls,
            )
        )
    await db.flush()
    await db.commit()


@pytest.mark.asyncio
async def test_not_enough_events_returns_none(db: AsyncSession):
    agent = await _seed_agent(db)
    await _add_events(db, agent, count=5)
    result = await compute_baseline(db, agent.id)
    assert result is None


@pytest.mark.asyncio
async def test_enough_events_returns_baseline(db: AsyncSession):
    agent = await _seed_agent(db)
    await _add_events(db, agent, count=MIN_EVENTS, token_count=100, latency_ms=200, model="gpt-4o")

    baseline = await compute_baseline(db, agent.id)
    assert baseline is not None
    assert baseline["avg_token_count"] == pytest.approx(100.0)
    assert baseline["avg_latency_ms"] == pytest.approx(200.0)
    assert baseline["std_token_count"] == pytest.approx(0.0, abs=0.1)
    assert baseline["std_latency_ms"] == pytest.approx(0.0, abs=0.1)
    assert "gpt-4o" in baseline["known_models"]
    assert baseline["event_count"] == MIN_EVENTS
    assert "computed_at" in baseline


@pytest.mark.asyncio
async def test_mixed_models_tracked(db: AsyncSession):
    agent = await _seed_agent(db)
    await _add_events(db, agent, count=15, model="gpt-4o")
    await _add_events(db, agent, count=10, model="claude-sonnet")

    baseline = await compute_baseline(db, agent.id)
    assert baseline is not None
    assert set(baseline["known_models"]) == {"gpt-4o", "claude-sonnet"}


@pytest.mark.asyncio
async def test_null_fields_handled(db: AsyncSession):
    """Events with null token_count/latency should not break computation."""
    agent = await _seed_agent(db)
    # Add events with null fields
    for _ in range(MIN_EVENTS):
        db.add(
            AgentEvent(
                agent_id=agent.id,
                timestamp=datetime.now(timezone.utc),
                prompt="test",
                response="test",
                model="gpt-4o",
                token_count=None,
                latency_ms=None,
            )
        )
    await db.flush()
    await db.commit()

    baseline = await compute_baseline(db, agent.id)
    assert baseline is not None
    assert baseline["avg_token_count"] == 0.0
    assert baseline["avg_latency_ms"] == 0.0
