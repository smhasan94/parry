"""Unit tests for serious_incident_service.

Pure helpers (``_build_report_content``, ``days_remaining``) are exercised
directly. The async functions are unit-tested with AsyncMock for the
DB layer — verifying error branches (NotFoundError / ConflictError),
deadline calculation, and the swallow-PDF-failure contract.

Full DB integration is covered by the e2e compliance suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import (
    Incident,
    IncidentStatus,
    SeriousIncident,
    Severity,
)
from app.services import serious_incident_service


def _make_incident(
    created_at: datetime | None = None,
    severity: Severity = Severity.CRITICAL,
) -> Incident:
    return Incident(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        title="Suspicious data exfiltration attempt",
        severity=severity,
        status=IncidentStatus.OPEN,
        created_at=created_at or datetime.now(UTC),
    )


def _make_report(
    deadline_at: datetime | None = None,
    reported_to_authority_at: datetime | None = None,
) -> SeriousIncident:
    return SeriousIncident(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        deadline_at=deadline_at or (datetime.now(UTC) + timedelta(days=10)),
        reported_to_authority_at=reported_to_authority_at,
        report_content={"description_of_incident": "draft"},
    )


def _execute_returning(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ── pure helpers ─────────────────────────────────────────────────────


def test_build_report_content_includes_incident_summary() -> None:
    incident = _make_incident()
    incident.resolved_at = None

    content = serious_incident_service._build_report_content(incident)

    summary = content["incident_summary"]
    assert summary["title"] == incident.title
    assert summary["severity"] == "critical"
    assert summary["status"] == "open"
    assert summary["detected_at"] == incident.created_at.isoformat()
    assert summary["resolved_at"] is None


def test_build_report_content_handles_missing_severity_and_status() -> None:
    incident = _make_incident()
    # Force-clear severity/status to confirm the guards in the helper.
    incident.severity = None  # type: ignore[assignment]
    incident.status = None  # type: ignore[assignment]

    content = serious_incident_service._build_report_content(incident)

    assert content["incident_summary"]["severity"] is None
    assert content["incident_summary"]["status"] is None


def test_build_report_content_seeds_user_fillable_fields_as_none() -> None:
    content = serious_incident_service._build_report_content(_make_incident())

    for field in (
        "description_of_incident",
        "affected_persons",
        "measures_taken",
        "root_cause_analysis",
        "corrective_actions",
    ):
        assert content[field] is None
    # Nested contact + authority dicts also start blank.
    assert all(v is None for v in content["contact_information"].values())
    assert all(v is None for v in content["authority_information"].values())


def test_days_remaining_returns_zero_once_finalized() -> None:
    report = _make_report(
        deadline_at=datetime.now(UTC) + timedelta(days=5),
        reported_to_authority_at=datetime.now(UTC),
    )
    assert serious_incident_service.days_remaining(report) == 0


def test_days_remaining_returns_positive_when_within_window() -> None:
    report = _make_report(deadline_at=datetime.now(UTC) + timedelta(days=10))
    assert 8 <= serious_incident_service.days_remaining(report) <= 10


def test_days_remaining_negative_when_overdue() -> None:
    report = _make_report(deadline_at=datetime.now(UTC) - timedelta(days=3))
    assert serious_incident_service.days_remaining(report) < 0


# ── create_draft ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_draft_raises_not_found_for_unknown_incident() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await serious_incident_service.create_draft(
            db, org_id=uuid.uuid4(), incident_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_create_draft_raises_conflict_when_report_already_exists() -> None:
    incident = _make_incident()
    existing = _make_report()
    db = AsyncMock()
    # First execute returns the incident, second returns an existing report.
    db.execute.side_effect = [
        _execute_returning(incident),
        _execute_returning(existing),
    ]

    with pytest.raises(ConflictError, match="already exists"):
        await serious_incident_service.create_draft(
            db, org_id=incident.org_id, incident_id=incident.id
        )


@pytest.mark.asyncio
async def test_create_draft_sets_15_day_deadline_from_incident_creation() -> None:
    detected_at = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    incident = _make_incident(created_at=detected_at)

    db = AsyncMock()
    db.execute.side_effect = [
        _execute_returning(incident),
        _execute_returning(None),  # no existing report
    ]
    db.add = MagicMock()
    db.refresh = AsyncMock()

    report = await serious_incident_service.create_draft(
        db,
        org_id=incident.org_id,
        incident_id=incident.id,
        created_by="user_alice",
    )

    assert report.deadline_at == detected_at + timedelta(days=15)
    assert report.created_by == "user_alice"
    assert report.report_content["incident_summary"]["title"] == incident.title
    db.add.assert_called_once()


# ── update_draft ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_draft_rejects_finalized_report() -> None:
    report = _make_report(reported_to_authority_at=datetime.now(UTC))
    db = AsyncMock()
    db.execute.return_value = _execute_returning(report)

    with pytest.raises(ConflictError, match="finalized"):
        await serious_incident_service.update_draft(
            db,
            org_id=report.org_id,
            report_id=report.id,
            report_content={"description_of_incident": "x"},
        )


@pytest.mark.asyncio
async def test_update_draft_merges_content_into_existing_report() -> None:
    report = _make_report()
    report.report_content = {
        "description_of_incident": "old",
        "measures_taken": "logged",
    }
    db = AsyncMock()
    db.execute.return_value = _execute_returning(report)

    await serious_incident_service.update_draft(
        db,
        org_id=report.org_id,
        report_id=report.id,
        report_content={"description_of_incident": "new", "root_cause_analysis": "RCA"},
        authority_jurisdiction="DE-BfDI",
    )

    assert report.report_content["description_of_incident"] == "new"
    assert report.report_content["measures_taken"] == "logged"
    assert report.report_content["root_cause_analysis"] == "RCA"
    assert report.authority_jurisdiction == "DE-BfDI"


# ── finalize ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_rejects_already_finalized_report() -> None:
    report = _make_report(reported_to_authority_at=datetime.now(UTC))
    db = AsyncMock()
    db.execute.return_value = _execute_returning(report)

    with pytest.raises(ConflictError, match="already finalized"):
        await serious_incident_service.finalize(
            db, report.org_id, report.id, finalized_by="user_alice"
        )


@pytest.mark.asyncio
async def test_finalize_sets_reported_at_and_renders_pdf() -> None:
    report = _make_report()
    db = AsyncMock()
    db.execute.return_value = _execute_returning(report)
    db.refresh = AsyncMock()

    with patch(
        "app.compliance.incident_report_template.render_incident_pdf",
        return_value=b"PDF-BYTES",
    ) as mock_render:
        result = await serious_incident_service.finalize(
            db, report.org_id, report.id, finalized_by="user_alice"
        )

    assert result.reported_to_authority_at is not None
    assert result.pdf_bytes == b"PDF-BYTES"
    mock_render.assert_called_once_with(report)


@pytest.mark.asyncio
async def test_finalize_swallows_pdf_render_failures() -> None:
    """A bad PDF render must not block finalization — the legal deadline
    matters more than the artefact, which can be regenerated later."""
    report = _make_report()
    db = AsyncMock()
    db.execute.return_value = _execute_returning(report)
    db.refresh = AsyncMock()

    with patch(
        "app.compliance.incident_report_template.render_incident_pdf",
        side_effect=RuntimeError("weasyprint exploded"),
    ):
        result = await serious_incident_service.finalize(
            db, report.org_id, report.id, finalized_by="user_alice"
        )

    assert result.reported_to_authority_at is not None
    assert result.pdf_bytes is None
