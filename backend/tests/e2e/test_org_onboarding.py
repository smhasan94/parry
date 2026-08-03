"""What a brand-new customer's org starts with.

Until now org creation inserted a bare row, so a customer's first five
minutes were an empty dashboard with nothing to react to and no obvious
first move. These defaults exist to give them somewhere to start —
without changing how anything behaves until they choose to.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentPermission, AuditLog, Org, Policy
from app.services import onboarding_service


async def _org(db: AsyncSession, name: str = "Acme") -> Org:
    org = Org(name=name, clerk_org_id=f"o_{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _permissions(db: AsyncSession, org: Org) -> list[AgentPermission]:
    result = await db.execute(select(AgentPermission).where(AgentPermission.org_id == org.id))
    return list(result.scalars().all())


async def _policies(db: AsyncSession, org: Org) -> list[Policy]:
    result = await db.execute(select(Policy).where(Policy.org_id == org.id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_a_new_org_gets_an_org_default_permission_boundary(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    perms = await _permissions(db, org)
    assert len(perms) == 1
    assert perms[0].agent_id is None  # org-wide default


@pytest.mark.asyncio
async def test_the_boundary_cannot_block_anything_on_day_one(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    boundary = (await _permissions(db, org))[0]
    # allow + empty lists denies nothing; dry_run means the first tool
    # they add to the blocklist is observed before it is enforced.
    assert boundary.mode == "dry_run"
    assert boundary.default_action == "allow"
    assert boundary.allowed_tools == []
    assert boundary.blocked_tools == []


@pytest.mark.asyncio
async def test_a_new_org_gets_an_inactive_starter_policy(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    policies = await _policies(db, org)
    assert len(policies) == 1
    # Detection only reads active policies, so an inactive one is inert.
    # It exists to be edited, not to take effect unreviewed.
    assert policies[0].is_active is False
    assert policies[0].description


@pytest.mark.asyncio
async def test_the_starter_policy_asserts_no_rules(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    policy = (await _policies(db, org))[0]
    # Agent tool names are application-specific. Shipping a guess at a
    # blocklist would produce false detections on a customer's first day.
    assert not policy.blocked_tools
    assert not policy.allowed_tools


@pytest.mark.asyncio
async def test_detector_config_is_left_unset(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    # Writing today's defaults into the row would freeze the org there,
    # and later tuning improvements would never reach them. None means
    # "use the platform defaults, whatever they currently are".
    assert org.detector_config is None


@pytest.mark.asyncio
async def test_provisioning_twice_creates_nothing_extra(db: AsyncSession):
    org = await _org(db)

    first = await onboarding_service.provision_new_org(db, org)
    second = await onboarding_service.provision_new_org(db, org)

    assert len(await _permissions(db, org)) == 1
    assert len(await _policies(db, org)) == 1
    assert first["provisioned"] is True
    assert second["provisioned"] is False


@pytest.mark.asyncio
async def test_an_org_that_already_configured_things_is_left_alone(db: AsyncSession):
    org = await _org(db)
    existing = AgentPermission(
        org_id=org.id, agent_id=None, mode="enforcing", default_action="deny"
    )
    db.add(existing)
    await db.flush()

    await onboarding_service.provision_new_org(db, org)

    perms = await _permissions(db, org)
    # Never overwrite a decision someone already made.
    assert len(perms) == 1
    assert perms[0].mode == "enforcing"


@pytest.mark.asyncio
async def test_provisioning_does_not_touch_other_orgs(db: AsyncSession):
    mine, theirs = await _org(db, "Mine"), await _org(db, "Theirs")

    await onboarding_service.provision_new_org(db, mine)

    assert await _permissions(db, theirs) == []
    assert await _policies(db, theirs) == []


@pytest.mark.asyncio
async def test_provisioning_is_audited(db: AsyncSession):
    org = await _org(db)

    await onboarding_service.provision_new_org(db, org)

    entries = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.org_id == org.id, AuditLog.action == "org.provisioned"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
