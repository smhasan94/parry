"""E2E test fixtures — real async DB, FastAPI test client, seeded org + API key."""

import hashlib
import os
import socket
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Agent, ApiKey, Org, Plan, Policy

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://parry:parry@localhost:5434/parry_test",
)


def _db_port_open() -> bool:
    try:
        sock = socket.create_connection(("localhost", 5434), timeout=1)
        sock.close()
        return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    """Skip all E2E tests when the test database is not reachable."""
    if _db_port_open():
        return
    skip_marker = pytest.mark.skip(
        reason="PostgreSQL test database not available on localhost:5434"
    )
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test: create engine, ensure tables, truncate, yield session."""
    test_engine = create_async_engine(TEST_DB_URL, echo=False)

    # Ensure tables exist
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Truncate all tables for isolation
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await test_engine.dispose()


@pytest.fixture
async def seeded_db(db: AsyncSession) -> dict:
    """Seed an org, API key, agent, and policy. Returns lookup dict."""
    # Use GROWTH tier so tests can freely create agents without
    # tripping the Free-tier 1-agent quota enforcement from plan-11.
    org = Org(
        name="E2E Test Org",
        clerk_org_id="clerk_e2e_test",
        is_active=True,
        plan=Plan.GROWTH,
    )
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
async def client(
    db: AsyncSession, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """HTTPX async client wired to FastAPI app with DB override.

    Also patches out Celery dispatch so tests don't hang on Redis
    connections. Detection pipeline is called directly in tests via
    run_and_persist_detections().

    **Auth note:** this fixture does NOT install an actor override,
    so dashboard routes gated by ``require_role`` reject the seeded
    API key (API keys resolve to VIEWER on the Bearer path since
    the security fix in 3ec13ee). Tests that exercise admin-level
    dashboard mutations should use the ``admin_client`` fixture
    instead, which stamps requests with an admin user actor via
    dependency_overrides.
    """
    from app.db.session import get_db
    from app.main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    # Patch Celery task dispatch to no-op (we call detection directly in tests)
    # The import happens inside the route function, so patch the source module
    monkeypatch.setattr(
        "app.workers.detection_task.run_detection_pipeline",
        type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_client(
    client: AsyncClient, seeded_db: dict
) -> AsyncGenerator[AsyncClient, None]:
    """Client that also installs an org:admin actor override.

    Bypasses the Clerk JWT verification path — every request through
    this client is treated as being made by an admin user in the
    seeded org. Use when a test needs to exercise admin-gated routes
    (PATCH /incidents, POST /agents, etc.). Runtime SDK paths
    (/proxy/check, /events/ingest) don't pass through this fixture
    and should still send X-Parry-Secret per request.
    """
    from app.core.dependencies import Actor, get_current_actor, get_current_org
    from app.main import app

    org = seeded_db["org"]
    admin_actor = Actor(
        actor_type="user",
        actor_id="admin-test",
        label="admin@example.com",
        clerk_role="org:owner",
    )

    async def _override_actor() -> tuple:
        return (org, admin_actor)

    async def _override_org():
        return org

    app.dependency_overrides[get_current_actor] = _override_actor
    app.dependency_overrides[get_current_org] = _override_org
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_current_org, None)
