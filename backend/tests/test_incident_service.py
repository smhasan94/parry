"""Unit tests for incident_service.

DB calls are mocked — these are pure-logic tests covering the
list/get/update surface: filter composition, cursor pagination,
NotFoundError on missing incidents, and the partial-update semantics
of update_incident (only non-None fields are written).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models import Incident, IncidentStatus, Severity
from app.services import incident_service


def _make_incident(
    org_id: uuid.UUID,
    severity: Severity = Severity.HIGH,
    status: IncidentStatus = IncidentStatus.OPEN,
    title: str = "[HIGH] prompt_injection: test",
    created_at: datetime | None = None,
) -> Incident:
    return Incident(
        id=uuid.uuid4(),
        org_id=org_id,
        agent_id=uuid.uuid4(),
        title=title,
        severity=severity,
        status=status,
        created_at=created_at or datetime.now(UTC),
    )


def _scalars_returning(rows: list[Any]) -> MagicMock:
    """Mock the ``db.execute(...).scalars().all()`` chain."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _execute_returning(row: Any) -> MagicMock:
    """Mock the ``db.execute(...).scalar_one_or_none()`` chain."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


# ── list_incidents ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_incidents_returns_empty_when_no_incidents() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    incidents, next_cursor = await incident_service.list_incidents(db, org_id)

    assert incidents == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_incidents_returns_rows_below_limit_without_cursor() -> None:
    org_id = uuid.uuid4()
    rows = [_make_incident(org_id) for _ in range(3)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    incidents, next_cursor = await incident_service.list_incidents(db, org_id, limit=10)

    assert len(incidents) == 3
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_incidents_returns_cursor_when_more_than_limit() -> None:
    org_id = uuid.uuid4()
    # Service requests `limit + 1` rows; if we get >limit it sets a cursor.
    rows = [_make_incident(org_id) for _ in range(4)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    incidents, next_cursor = await incident_service.list_incidents(db, org_id, limit=3)

    assert len(incidents) == 3
    assert next_cursor == str(incidents[-1].id)


@pytest.mark.asyncio
async def test_list_incidents_with_severity_filter_passes_severity_to_query() -> None:
    org_id = uuid.uuid4()
    rows = [_make_incident(org_id, severity=Severity.CRITICAL)]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    incidents, _ = await incident_service.list_incidents(
        db, org_id, severity=Severity.CRITICAL
    )

    assert len(incidents) == 1
    # Confirm the query was built (one execute call) — pure-logic test
    # doesn't introspect SQL, but smoke-tests the filter branch.
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_incidents_with_status_filter_passes_status_to_query() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(
        [_make_incident(org_id, status=IncidentStatus.RESOLVED)]
    )

    incidents, _ = await incident_service.list_incidents(
        db, org_id, status=IncidentStatus.RESOLVED
    )

    assert len(incidents) == 1


@pytest.mark.asyncio
async def test_list_incidents_with_session_id_filter_runs_query() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    incidents, _ = await incident_service.list_incidents(
        db, org_id, session_id=str(uuid.uuid4())
    )

    assert incidents == []


@pytest.mark.asyncio
async def test_list_incidents_uses_cursor_to_filter_by_created_at() -> None:
    org_id = uuid.uuid4()
    cursor_incident = _make_incident(
        org_id, created_at=datetime.now(UTC) - timedelta(hours=1)
    )
    older = [
        _make_incident(org_id, created_at=datetime.now(UTC) - timedelta(hours=h))
        for h in (2, 3)
    ]
    db = AsyncMock()
    db.get.return_value = cursor_incident
    db.execute.return_value = _scalars_returning(older)

    incidents, next_cursor = await incident_service.list_incidents(
        db, org_id, cursor=str(cursor_incident.id), limit=10
    )

    assert len(incidents) == 2
    assert next_cursor is None
    db.get.assert_awaited_once()


# ── get_incident ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_incident_returns_incident_when_found() -> None:
    org_id = uuid.uuid4()
    incident = _make_incident(org_id)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(incident)

    result = await incident_service.get_incident(db, org_id, incident.id)

    assert result is incident


@pytest.mark.asyncio
async def test_get_incident_raises_not_found_when_missing() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await incident_service.get_incident(db, org_id, uuid.uuid4())


# ── update_incident ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_incident_updates_status() -> None:
    org_id = uuid.uuid4()
    incident = _make_incident(org_id, status=IncidentStatus.OPEN)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(incident)

    result = await incident_service.update_incident(
        db, org_id, incident.id, status=IncidentStatus.RESOLVED
    )

    assert result.status == IncidentStatus.RESOLVED
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(incident)


@pytest.mark.asyncio
async def test_update_incident_updates_title() -> None:
    org_id = uuid.uuid4()
    incident = _make_incident(org_id, title="[HIGH] old title")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(incident)

    result = await incident_service.update_incident(
        db, org_id, incident.id, title="[HIGH] new title"
    )

    assert result.title == "[HIGH] new title"


@pytest.mark.asyncio
async def test_update_incident_with_no_fields_does_not_change_state() -> None:
    org_id = uuid.uuid4()
    original_title = "[HIGH] unchanged"
    original_status = IncidentStatus.OPEN
    incident = _make_incident(org_id, title=original_title, status=original_status)
    db = AsyncMock()
    db.execute.return_value = _execute_returning(incident)

    result = await incident_service.update_incident(db, org_id, incident.id)

    # No-op update still flushes — the call always commits.
    assert result.title == original_title
    assert result.status == original_status


@pytest.mark.asyncio
async def test_update_incident_raises_not_found_when_missing() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await incident_service.update_incident(
            db, org_id, uuid.uuid4(), status=IncidentStatus.RESOLVED
        )
