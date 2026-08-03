"""Tests for Clerk webhook handler logic."""

import os
import socket

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.webhooks import (
    _handle_org_created,
    _handle_org_deleted,
    _handle_org_updated,
    _handle_user_created,
)
from app.db.base import Base
from app.db.models import Org

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


pytestmark = pytest.mark.skipif(
    not _db_port_open(),
    reason="PostgreSQL test database not available on localhost:5434",
)


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_org_created(db: AsyncSession):
    """organization.created creates a new Org."""
    await _handle_org_created(db, {"id": "org_clerk_123", "name": "Acme Corp"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_123"))
    org = result.scalar_one()
    assert org.name == "Acme Corp"
    assert org.is_active is True


@pytest.mark.asyncio
async def test_org_created_idempotent(db: AsyncSession):
    """Duplicate organization.created does not create a second Org."""
    db.add(Org(name="Existing", clerk_org_id="org_clerk_dup", is_active=True))
    await db.flush()
    await db.commit()

    await _handle_org_created(db, {"id": "org_clerk_dup", "name": "Duplicate"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_dup"))
    orgs = list(result.scalars().all())
    assert len(orgs) == 1
    assert orgs[0].name == "Existing"


@pytest.mark.asyncio
async def test_org_updated(db: AsyncSession):
    """organization.updated renames the Org."""
    db.add(Org(name="Old Name", clerk_org_id="org_clerk_upd", is_active=True))
    await db.flush()
    await db.commit()

    await _handle_org_updated(db, {"id": "org_clerk_upd", "name": "New Name"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_upd"))
    org = result.scalar_one()
    assert org.name == "New Name"


@pytest.mark.asyncio
async def test_org_updated_not_found(db: AsyncSession):
    """organization.updated for unknown org is a no-op."""
    await _handle_org_updated(db, {"id": "org_nonexistent", "name": "Nope"})
    await db.commit()
    # Should not raise


@pytest.mark.asyncio
async def test_org_deleted(db: AsyncSession):
    """organization.deleted deactivates the Org."""
    db.add(Org(name="To Delete", clerk_org_id="org_clerk_del", is_active=True))
    await db.flush()
    await db.commit()

    await _handle_org_deleted(db, {"id": "org_clerk_del"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_del"))
    org = result.scalar_one()
    assert org.is_active is False


@pytest.mark.asyncio
async def test_org_deleted_not_found(db: AsyncSession):
    """organization.deleted for unknown org is a no-op."""
    await _handle_org_deleted(db, {"id": "org_nonexistent"})
    await db.commit()


@pytest.mark.asyncio
async def test_user_created(db: AsyncSession):
    """user.created creates a personal workspace Org."""
    await _handle_user_created(
        db,
        {
            "id": "user_clerk_abc",
            "first_name": "Jane",
            "last_name": "Doe",
        },
    )
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "user_clerk_abc"))
    org = result.scalar_one()
    assert org.name == "Jane Doe's Workspace"
    assert org.is_active is True


@pytest.mark.asyncio
async def test_user_created_idempotent(db: AsyncSession):
    """Duplicate user.created does not create a second Org."""
    db.add(Org(name="Existing Workspace", clerk_org_id="user_dup", is_active=True))
    await db.flush()
    await db.commit()

    await _handle_user_created(db, {"id": "user_dup", "first_name": "Test"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "user_dup"))
    orgs = list(result.scalars().all())
    assert len(orgs) == 1


@pytest.mark.asyncio
async def test_user_created_no_name(db: AsyncSession):
    """user.created without a name defaults to 'Personal's Workspace'."""
    await _handle_user_created(db, {"id": "user_noname"})
    await db.commit()

    result = await db.execute(select(Org).where(Org.clerk_org_id == "user_noname"))
    org = result.scalar_one()
    assert org.name == "Personal's Workspace"


@pytest.mark.asyncio
async def test_org_created_provisions_starting_config(db: AsyncSession):
    """A customer signing up gets somewhere to start, not a blank slate."""
    from app.db.models import AgentPermission, Policy

    await _handle_org_created(db, {"id": "org_clerk_prov", "name": "Provisioned Co"})
    await db.commit()

    org = (await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_prov"))).scalar_one()

    perms = (
        (await db.execute(select(AgentPermission).where(AgentPermission.org_id == org.id)))
        .scalars()
        .all()
    )
    policies = (await db.execute(select(Policy).where(Policy.org_id == org.id))).scalars().all()

    assert len(perms) == 1
    assert perms[0].mode == "dry_run"
    assert len(policies) == 1
    assert policies[0].is_active is False


@pytest.mark.asyncio
async def test_a_personal_workspace_is_provisioned_too(db: AsyncSession):
    """The user.created path creates an org as well, and was missed."""
    from app.db.models import AgentPermission

    await _handle_user_created(
        db,
        {
            "id": "user_clerk_prov",
            "first_name": "Ada",
            "email_addresses": [{"email_address": "ada@corp.com"}],
        },
    )
    await db.commit()

    org = (await db.execute(select(Org).where(Org.clerk_org_id == "user_clerk_prov"))).scalar_one()
    perms = (
        (await db.execute(select(AgentPermission).where(AgentPermission.org_id == org.id)))
        .scalars()
        .all()
    )

    assert len(perms) == 1


@pytest.mark.asyncio
async def test_a_replayed_org_webhook_does_not_duplicate_config(db: AsyncSession):
    from app.db.models import Policy

    payload = {"id": "org_clerk_replay", "name": "Replay Co"}
    await _handle_org_created(db, payload)
    await _handle_org_created(db, payload)
    await db.commit()

    org = (await db.execute(select(Org).where(Org.clerk_org_id == "org_clerk_replay"))).scalar_one()
    policies = (await db.execute(select(Policy).where(Policy.org_id == org.id))).scalars().all()

    # Clerk retries deliveries; a retry must not double the config.
    assert len(policies) == 1
