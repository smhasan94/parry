"""E2E test fixtures — real async DB, FastAPI test client, seeded org + API key."""
import hashlib
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Agent, ApiKey, Org, Policy

TEST_DB_URL = "postgresql+asyncpg://parry:parry@localhost:5434/parry_test"

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create all tables once per test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test DB session — each test starts with clean tables."""
    # Truncate all tables between tests for full isolation
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))

    async with TestSessionFactory() as session:
        yield session


@pytest.fixture
async def seeded_db(db: AsyncSession) -> dict:
    """Seed an org, API key, agent, and policy. Returns lookup dict."""
    org = Org(name="E2E Test Org", clerk_org_id="clerk_e2e_test", is_active=True)
    db.add(org)
    await db.flush()

    raw_key = f"sk-parry-e2e-{uuid.uuid4().hex[:16]}"
    api_key = ApiKey(
        org_id=org.id,
        name="e2e-key",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        key_prefix=raw_key[:14],
        is_active=True,
    )
    db.add(api_key)

    agent = Agent(org_id=org.id, name="e2e-agent", description="E2E test agent", is_active=True)
    db.add(agent)

    policy = Policy(
        org_id=org.id,
        name="e2e-policy",
        is_active=True,
        allowed_tools=["search", "read_file"],
        blocked_tools=["exec_code", "shell"],
    )
    db.add(policy)
    await db.flush()
    await db.commit()

    return {
        "org": org,
        "api_key_raw": raw_key,
        "api_key": api_key,
        "agent": agent,
        "policy": policy,
    }


@pytest.fixture
async def client(db: AsyncSession, seeded_db: dict) -> AsyncGenerator[AsyncClient, None]:
    """HTTPX async client wired to FastAPI app with DB override."""
    from app.db.session import get_db
    from app.main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
