"""Unit tests for ai_system_service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models import AISystem, AISystemSupplier
from app.services import ai_system_service


def _make_system(
    org_id: uuid.UUID | None = None,
    risk_level: str = "minimal",
    fria_required: bool = False,
    fria_status: str = "not_required",
) -> AISystem:
    return AISystem(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        name="Test System",
        risk_level=risk_level,
        intended_purpose="testing",
        fria_required=fria_required,
        fria_status=fria_status,
        agent_ids=[],
    )


def _scalars_returning(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _scalar_one_or_none(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


# ── list_systems ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_systems_returns_all_for_org() -> None:
    org_id = uuid.uuid4()
    systems = [_make_system(org_id), _make_system(org_id)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(systems)

    result, next_cursor = await ai_system_service.list_systems(db, org_id)

    assert result == systems
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_systems_paginates_when_over_limit() -> None:
    org_id = uuid.uuid4()
    systems = [_make_system(org_id) for _ in range(51)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(systems)

    result, next_cursor = await ai_system_service.list_systems(db, org_id, limit=50)

    assert len(result) == 50
    assert next_cursor == str(systems[49].id)


@pytest.mark.asyncio
async def test_list_systems_returns_empty_list_for_unknown_org() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    result, next_cursor = await ai_system_service.list_systems(db, uuid.uuid4())

    assert result == []
    assert next_cursor is None


# ── get_system ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_system_returns_system() -> None:
    org_id = uuid.uuid4()
    system = _make_system(org_id)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(system)

    result = await ai_system_service.get_system(db, org_id, system.id)

    assert result is system


@pytest.mark.asyncio
async def test_get_system_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await ai_system_service.get_system(db, uuid.uuid4(), uuid.uuid4())


# ── create_system ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_system_low_risk_sets_fria_not_required() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await ai_system_service.create_system(
        db, org_id, name="Low Risk", risk_level="minimal", intended_purpose="testing"
    )

    assert result.fria_required is False
    assert result.fria_status == "not_required"
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_system_high_risk_sets_fria_required_and_missing() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await ai_system_service.create_system(
        db, org_id, name="High Risk", risk_level="high", intended_purpose="biometric"
    )

    assert result.fria_required is True
    assert result.fria_status == "missing"


@pytest.mark.asyncio
async def test_create_system_sets_agent_ids_to_empty_list_when_none() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await ai_system_service.create_system(
        db, org_id, name="Sys", risk_level="limited", intended_purpose="x"
    )

    assert result.agent_ids == []


@pytest.mark.asyncio
async def test_create_system_accepts_optional_provider_fields() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()

    result = await ai_system_service.create_system(
        db,
        org_id,
        name="Full",
        risk_level="high",
        intended_purpose="biometric",
        provider_name="Acme AI",
        provider_contact="ai@acme.com",
        deployer_name="Acme Corp",
        annex_iii_category="cat_b",
        jurisdiction="EU",
    )

    assert result.provider_name == "Acme AI"
    assert result.jurisdiction == "EU"


# ── update_system ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_system_changes_risk_to_high_derives_fria_required() -> None:
    org_id = uuid.uuid4()
    system = _make_system(org_id, risk_level="minimal")
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(system)

    result = await ai_system_service.update_system(
        db, org_id, system.id, risk_level="high"
    )

    assert result.fria_required is True
    assert result.fria_status == "missing"


@pytest.mark.asyncio
async def test_update_system_changes_risk_from_high_to_low_clears_fria() -> None:
    org_id = uuid.uuid4()
    system = _make_system(org_id, risk_level="high", fria_required=True, fria_status="missing")
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(system)

    result = await ai_system_service.update_system(
        db, org_id, system.id, risk_level="minimal"
    )

    assert result.fria_required is False
    assert result.fria_status == "not_required"


@pytest.mark.asyncio
async def test_update_system_skips_none_values() -> None:
    org_id = uuid.uuid4()
    system = _make_system(org_id)
    system.description = "original"
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(system)

    await ai_system_service.update_system(db, org_id, system.id, description=None)

    assert system.description == "original"


@pytest.mark.asyncio
async def test_update_system_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await ai_system_service.update_system(db, uuid.uuid4(), uuid.uuid4(), name="x")


# ── delete_system ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_system_calls_delete_and_flush() -> None:
    org_id = uuid.uuid4()
    system = _make_system(org_id)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(system)

    await ai_system_service.delete_system(db, org_id, system.id)

    db.delete.assert_awaited_once_with(system)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_system_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    with pytest.raises(NotFoundError):
        await ai_system_service.delete_system(db, uuid.uuid4(), uuid.uuid4())


# ── list_suppliers ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_suppliers_returns_suppliers_for_system() -> None:
    system_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    supplier = AISystemSupplier(
        id=uuid.uuid4(),
        system_id=system_id,
        supplier_name="openai",
        model_id="gpt-4o",
        first_used_at=now,
        last_used_at=now,
        event_count=10,
    )
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([supplier])

    result = await ai_system_service.list_suppliers(db, system_id)

    assert result == [supplier]


@pytest.mark.asyncio
async def test_list_suppliers_returns_empty_list_when_none() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    result = await ai_system_service.list_suppliers(db, uuid.uuid4())

    assert result == []
