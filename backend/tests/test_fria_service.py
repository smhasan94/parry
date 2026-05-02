"""Unit tests for fria_service.

DB layer is mocked. We pin down the workflow guards (only-draft can be
edited / approved), version incrementing, status transitions, the
365-day review-window default, the swallow-PDF-failure contract on
approval, and the source→field resolution in ``_populate_section``.
Full template integration is covered by the e2e compliance suite.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import AISystem, FRIADocument
from app.services import fria_service


def _make_system(org_id: uuid.UUID | None = None) -> AISystem:
    return AISystem(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        name="Hiring Triage Bot",
        risk_level="high",
        intended_purpose="Resume screening",
        annex_iii_category="employment",
        deployer_name="Acme Corp",
        agent_ids=[],
    )


def _make_fria(status: str = "draft", system_id: uuid.UUID | None = None) -> FRIADocument:
    return FRIADocument(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        system_id=system_id or uuid.uuid4(),
        version=1,
        status=status,
        content={"template_version": "1.0", "sections": {}},
    )


def _execute_returning(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _execute_scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _execute_scalars(values: list[object]) -> MagicMock:
    result = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = values
    result.scalars.return_value = scalars_proxy
    return result


# ── get_fria ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_fria_raises_not_found_when_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await fria_service.get_fria(db, uuid.uuid4(), uuid.uuid4())


# ── update_fria ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_fria_rejects_non_draft_status() -> None:
    fria = _make_fria(status="approved")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(fria)

    with pytest.raises(ConflictError, match="draft"):
        await fria_service.update_fria(
            db, fria.org_id, fria.id, content_updates={"x": {"y": 1}}
        )


@pytest.mark.asyncio
async def test_update_fria_merges_per_section_into_existing_content() -> None:
    fria = _make_fria()
    fria.content = {
        "template_version": "1.0",
        "sections": {
            "context_of_use": {
                "title": "2. Context of Use",
                "fields": {"geographic_scope": "EU", "user_population": "all"},
            },
        },
    }
    db = AsyncMock()
    db.execute.return_value = _execute_returning(fria)

    await fria_service.update_fria(
        db,
        fria.org_id,
        fria.id,
        content_updates={
            "context_of_use": {
                "fields": {"geographic_scope": "EU+UK"},
            },
            "affected_populations": {"fields": {"groups": "candidates"}},
        },
    )

    sections = fria.content["sections"]
    # Existing section field replaced (full sub-dict update — not deep merge)
    assert sections["context_of_use"]["fields"] == {"geographic_scope": "EU+UK"}
    # Title preserved on the touched section.
    assert sections["context_of_use"]["title"] == "2. Context of Use"
    # New section appended.
    assert sections["affected_populations"] == {"fields": {"groups": "candidates"}}


# ── approve_fria ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_fria_rejects_non_draft_status() -> None:
    fria = _make_fria(status="archived")
    db = AsyncMock()
    db.execute.return_value = _execute_returning(fria)

    with pytest.raises(ConflictError, match="draft"):
        await fria_service.approve_fria(
            db, fria.org_id, fria.id, approved_by="user_alice"
        )


@pytest.mark.asyncio
async def test_approve_fria_sets_status_review_date_and_archives_prior_versions() -> None:
    fria = _make_fria()
    system = _make_system()
    fria.system_id = system.id
    prior_approved = _make_fria(status="approved", system_id=system.id)

    db = AsyncMock()
    # 1) get_fria(...)
    # 2) prior approved versions for this system
    # 3) load AISystem to flip fria_status
    db.execute.side_effect = [
        _execute_returning(fria),
        _execute_scalars([prior_approved]),
        _execute_returning(system),
    ]
    db.refresh = AsyncMock()

    with patch(
        "app.compliance.fria_html_template.render_fria_pdf",
        return_value=b"PDF",
    ):
        result = await fria_service.approve_fria(
            db,
            fria.org_id,
            fria.id,
            approved_by="user_alice",
            approver_title="DPO",
        )

    assert result.status == "approved"
    assert result.approved_by == "user_alice"
    assert result.approver_title == "DPO"
    # 365-day review window from today.
    assert result.next_review_date is not None
    assert result.next_review_date - date.today() == timedelta(days=365)
    assert result.pdf_bytes == b"PDF"
    # Prior approved version archived.
    assert prior_approved.status == "archived"
    # System reflects the approval.
    assert system.fria_status == "approved"


@pytest.mark.asyncio
async def test_approve_fria_swallows_pdf_render_failures() -> None:
    """Approval must complete even if PDF rendering crashes — the legal
    record is the row, not the artefact."""
    fria = _make_fria()
    system = _make_system()
    fria.system_id = system.id

    db = AsyncMock()
    db.execute.side_effect = [
        _execute_returning(fria),
        _execute_scalars([]),
        _execute_returning(system),
    ]
    db.refresh = AsyncMock()

    with patch(
        "app.compliance.fria_html_template.render_fria_pdf",
        side_effect=RuntimeError("boom"),
    ):
        result = await fria_service.approve_fria(
            db, fria.org_id, fria.id, approved_by="user_alice"
        )

    assert result.status == "approved"
    assert result.pdf_bytes is None


# ── generate_fria ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_fria_raises_not_found_when_system_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _execute_returning(None)

    with pytest.raises(NotFoundError):
        await fria_service.generate_fria(db, uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_generate_fria_increments_version_from_existing_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = _make_system()
    db = AsyncMock()
    # 1) load system, 2) max(version) -> 3, 3..n) _build_content fan-out.
    # We stub _build_content so we don't need to mock the whole template walk.
    monkeypatch.setattr(
        fria_service,
        "_build_content",
        AsyncMock(return_value={"template_version": "1.0", "sections": {}}),
    )
    db.execute.side_effect = [
        _execute_returning(system),
        _execute_scalar(3),
    ]
    db.add = MagicMock()
    db.refresh = AsyncMock()

    doc = await fria_service.generate_fria(
        db, system.org_id, system.id, generated_by="user_alice"
    )

    assert doc.version == 4
    assert doc.status == "draft"
    assert doc.generated_by == "user_alice"
    assert system.fria_status == "draft"


# ── _populate_section ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_populate_section_resolves_ai_systems_attrs() -> None:
    system = _make_system()
    db = AsyncMock()

    fields = await fria_service._populate_section(
        db,
        system.org_id,
        system,
        {
            "id": "x",
            "fields": [
                {"key": "name", "source": "ai_systems.name"},
                {"key": "risk", "source": "ai_systems.risk_level"},
                {"key": "missing_attr", "source": "ai_systems.does_not_exist"},
            ],
        },
    )

    assert fields["name"] == "Hiring Triage Bot"
    assert fields["risk"] == "high"
    assert fields["missing_attr"] is None


@pytest.mark.asyncio
async def test_populate_section_returns_none_for_unknown_source() -> None:
    system = _make_system()
    db = AsyncMock()

    fields = await fria_service._populate_section(
        db,
        system.org_id,
        system,
        {
            "id": "x",
            "fields": [{"key": "blank", "source": "definitely-not-a-source"}],
        },
    )

    assert fields == {"blank": None}


@pytest.mark.asyncio
async def test_populate_section_computed_field_uses_known_table() -> None:
    system = _make_system()
    db = AsyncMock()

    fields = await fria_service._populate_section(
        db,
        system.org_id,
        system,
        {
            "id": "oversight",
            "fields": [
                {"key": "human_oversight_rbac", "source": "computed"},
                {"key": "audit_log_retention", "source": "computed"},
                # Unknown computed key returns None gracefully.
                {"key": "not_in_table", "source": "computed"},
            ],
        },
    )

    assert "RBAC" in fields["human_oversight_rbac"]
    assert "tamper-evident" in fields["audit_log_retention"]
    assert fields["not_in_table"] is None
