"""Unit tests for compliance_posture_service."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import AISystem, Org, Severity
from app.services.compliance_posture_service import (
    Obligation,
    _check_fria,
    _check_human_oversight,
    _check_serious_incidents,
    _check_suspension,
    _check_usage_logs,
    compute_posture,
    get_posture,
    overall_status,
)

_NOW = datetime.now(timezone.utc)


def _scalar_one(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _scalar_one_or_none(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_returning(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _make_org(blocking_enabled: bool = True, detector_config: dict | None = None) -> Org:
    return Org(
        id=uuid.uuid4(),
        name="Acme",
        clerk_org_id=f"c_{uuid.uuid4().hex[:8]}",
        is_active=True,
        blocking_enabled=blocking_enabled,
        detector_config=detector_config or {"enabled": True},
    )


def _make_ai_system(risk_level: str = "high", fria_status: str = "missing") -> AISystem:
    return AISystem(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name=f"System-{fria_status}",
        risk_level=risk_level,
        intended_purpose="testing",
        fria_required=(risk_level == "high"),
        fria_status=fria_status,
        agent_ids=[],
    )


# ── overall_status (pure) ─────────────────────────────────────────


def test_overall_status_all_green_returns_green() -> None:
    obs = [
        Obligation(id="a", article="A", title="A", status="green"),
        Obligation(id="b", article="B", title="B", status="green"),
    ]
    assert overall_status(obs) == "green"


def test_overall_status_red_beats_yellow() -> None:
    obs = [
        Obligation(id="a", article="A", title="A", status="yellow"),
        Obligation(id="b", article="B", title="B", status="red"),
    ]
    assert overall_status(obs) == "red"


def test_overall_status_yellow_beats_green() -> None:
    obs = [
        Obligation(id="a", article="A", title="A", status="green"),
        Obligation(id="b", article="B", title="B", status="yellow"),
    ]
    assert overall_status(obs) == "yellow"


def test_overall_status_all_na_returns_na() -> None:
    obs = [Obligation(id="a", article="A", title="A", status="na")]
    assert overall_status(obs) == "na"


def test_overall_status_na_ignored_when_green_present() -> None:
    obs = [
        Obligation(id="a", article="A", title="A", status="na"),
        Obligation(id="b", article="B", title="B", status="green"),
    ]
    assert overall_status(obs) == "green"


# ── get_posture — cache paths ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_posture_returns_cached_obligations_on_redis_hit() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    cached = [
        {
            "id": "art_26_6_usage_logs",
            "article": "Art. 26(6)",
            "title": "Maintain usage logs",
            "status": "green",
            "evidence": {},
            "remediation": None,
        }
    ]
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps(cached)

    with patch(
        "app.services.compliance_posture_service._get_redis", return_value=fake_redis
    ), patch(
        "app.services.compliance_posture_service.compute_posture"
    ) as mock_compute:
        result = await get_posture(db, org_id)

    assert len(result) == 1
    assert result[0].id == "art_26_6_usage_logs"
    mock_compute.assert_not_called()


@pytest.mark.asyncio
async def test_get_posture_computes_on_cache_miss() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    computed = [Obligation(id="x", article="A", title="T", status="green")]

    fake_redis = MagicMock()
    fake_redis.get.return_value = None

    with patch(
        "app.services.compliance_posture_service._get_redis", return_value=fake_redis
    ), patch(
        "app.services.compliance_posture_service.compute_posture",
        return_value=computed,
    ) as mock_compute:
        result = await get_posture(db, org_id)

    mock_compute.assert_awaited_once_with(db, org_id)
    assert result == computed


@pytest.mark.asyncio
async def test_get_posture_computes_when_redis_unavailable() -> None:
    org_id = uuid.uuid4()
    db = AsyncMock()
    computed = [Obligation(id="x", article="A", title="T", status="green")]

    with patch(
        "app.services.compliance_posture_service._get_redis", return_value=None
    ), patch(
        "app.services.compliance_posture_service.compute_posture",
        return_value=computed,
    ) as mock_compute:
        result = await get_posture(db, org_id)

    mock_compute.assert_awaited_once_with(db, org_id)
    assert result == computed


# ── _check_usage_logs ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_usage_logs_green_when_audit_rows_exist() -> None:
    db = AsyncMock()
    db.execute.side_effect = [_scalar_one(25), _scalar_one_or_none(None)]

    ob = await _check_usage_logs(db, uuid.uuid4())

    assert ob.status == "green"
    assert ob.evidence["audit_log_rows"] == 25


@pytest.mark.asyncio
async def test_check_usage_logs_red_when_no_audit_rows() -> None:
    db = AsyncMock()
    db.execute.side_effect = [_scalar_one(0), _scalar_one_or_none(None)]

    ob = await _check_usage_logs(db, uuid.uuid4())

    assert ob.status == "red"
    assert ob.remediation is not None


@pytest.mark.asyncio
async def test_check_usage_logs_includes_last_export_when_present() -> None:
    db = AsyncMock()
    export_time = _NOW - timedelta(days=5)
    db.execute.side_effect = [_scalar_one(10), _scalar_one_or_none(export_time)]

    ob = await _check_usage_logs(db, uuid.uuid4())

    assert ob.evidence["last_export_at"] is not None


# ── _check_human_oversight ────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_human_oversight_green_when_org_exists() -> None:
    org = _make_org()
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(org)

    ob = await _check_human_oversight(db, org.id)

    assert ob.status == "green"
    assert ob.evidence["org_active"] is True


@pytest.mark.asyncio
async def test_check_human_oversight_red_when_org_missing() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(None)

    ob = await _check_human_oversight(db, uuid.uuid4())

    assert ob.status == "red"


# ── _check_suspension ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_suspension_green_when_blocking_enabled() -> None:
    org = _make_org(blocking_enabled=True)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(org)

    ob = await _check_suspension(db, org.id)

    assert ob.status == "green"
    assert ob.evidence["blocking_mode_enabled"] is True


@pytest.mark.asyncio
async def test_check_suspension_yellow_when_blocking_disabled() -> None:
    org = _make_org(blocking_enabled=False)
    db = AsyncMock()
    db.execute.return_value = _scalar_one_or_none(org)

    ob = await _check_suspension(db, org.id)

    assert ob.status == "yellow"
    assert ob.remediation is not None


# ── _check_fria ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_fria_na_when_no_high_risk_systems() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "na"
    assert ob.evidence["high_risk_systems"] == 0


@pytest.mark.asyncio
async def test_check_fria_red_when_any_missing_fria() -> None:
    system = _make_ai_system(risk_level="high", fria_status="missing")
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([system])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "red"
    assert system.name in ob.evidence["missing_fria"]


@pytest.mark.asyncio
async def test_check_fria_yellow_when_stale_fria() -> None:
    system = _make_ai_system(risk_level="high", fria_status="stale")
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([system])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "yellow"


@pytest.mark.asyncio
async def test_check_fria_yellow_when_draft_fria() -> None:
    system = _make_ai_system(risk_level="high", fria_status="draft")
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([system])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "yellow"


@pytest.mark.asyncio
async def test_check_fria_green_when_all_approved() -> None:
    system = _make_ai_system(risk_level="high", fria_status="approved")
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([system])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "green"


@pytest.mark.asyncio
async def test_check_fria_red_beats_stale_when_mixed() -> None:
    missing = _make_ai_system(risk_level="high", fria_status="missing")
    stale = _make_ai_system(risk_level="high", fria_status="stale")
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([missing, stale])

    ob = await _check_fria(db, uuid.uuid4())

    assert ob.status == "red"


# ── _check_serious_incidents ──────────────────────────────────────


@pytest.mark.asyncio
async def test_check_serious_incidents_green_when_no_critical() -> None:
    db = AsyncMock()
    db.execute.return_value = _scalars_returning([])

    ob = await _check_serious_incidents(db, uuid.uuid4())

    assert ob.status == "green"
    assert ob.evidence["critical_incidents_30d"] == 0


@pytest.mark.asyncio
async def test_check_serious_incidents_yellow_when_unreported_but_not_overdue() -> None:
    incident = MagicMock()
    incident.id = uuid.uuid4()
    incident.created_at = _NOW - timedelta(days=3)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalars_returning([incident]),
        _scalar_one_or_none(None),
    ]

    ob = await _check_serious_incidents(db, uuid.uuid4())

    assert ob.status == "yellow"
    assert ob.evidence["unreported_count"] == 1
    assert ob.evidence["overdue_count"] == 0


@pytest.mark.asyncio
async def test_check_serious_incidents_red_when_overdue() -> None:
    incident = MagicMock()
    incident.id = uuid.uuid4()
    incident.created_at = _NOW - timedelta(days=20)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalars_returning([incident]),
        _scalar_one_or_none(None),
    ]

    ob = await _check_serious_incidents(db, uuid.uuid4())

    assert ob.status == "red"
    assert ob.evidence["overdue_count"] == 1


@pytest.mark.asyncio
async def test_check_serious_incidents_green_when_all_reported() -> None:
    incident = MagicMock()
    incident.id = uuid.uuid4()
    incident.created_at = _NOW - timedelta(days=5)

    report = MagicMock()
    report.reported_to_authority_at = _NOW - timedelta(days=3)

    db = AsyncMock()
    db.execute.side_effect = [
        _scalars_returning([incident]),
        _scalar_one_or_none(report),
    ]

    ob = await _check_serious_incidents(db, uuid.uuid4())

    assert ob.status == "green"
    assert ob.evidence["unreported_count"] == 0
