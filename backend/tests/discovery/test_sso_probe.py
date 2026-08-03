"""Unit tests for the SSO probe processor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import AICatalogEntry
from app.discovery.sso_probe import SSOProbeProcessor


def _catalog_entry(service_name: str = "Notion AI") -> AICatalogEntry:
    return AICatalogEntry(
        id=uuid.uuid4(),
        service_name=service_name,
        vendor="Notion",
        category="productivity",
        default_risk_tier="limited",
    )


def _matcher(entry_id: uuid.UUID | None) -> MagicMock:
    matcher = MagicMock()
    matcher.match.return_value = entry_id
    return matcher


def _db(*, inserted: bool = True, catalog_entry: AICatalogEntry | None = None) -> MagicMock:
    """A db whose upsert reports insert-vs-conflict and whose catalog
    lookup returns ``catalog_entry``."""
    db = MagicMock()
    upsert_result = MagicMock()
    upsert_result.one.return_value = MagicMock(inserted=inserted)
    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = catalog_entry
    db.execute = AsyncMock(side_effect=[upsert_result, lookup_result])
    db.flush = AsyncMock()
    return db


def _raw_event(app_name: str = "Notion AI", user: str = "ada@corp.com") -> dict:
    return {
        "timestamp": "2026-03-01T09:00:00Z",
        "provider": "okta",
        "oauth_app_id": "0oa1notion",
        "app_name": app_name,
        "user_identifier": user,
        "grant_type": "admin_assigned",
        "status": "active",
    }


async def test_matched_event_reconciles_a_register_row() -> None:
    org_id = uuid.uuid4()
    entry = _catalog_entry()
    db = _db(catalog_entry=entry)
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()) as reconcile:
        result = await processor.process(db=db, org_id=org_id, events=[_raw_event()])

    assert result.matched == 1
    assert result.unmatched == 0
    reconcile.assert_awaited_once()
    assert reconcile.await_args.kwargs["org_id"] == org_id
    assert reconcile.await_args.kwargs["catalog_entry"] is entry
    assert reconcile.await_args.kwargs["discovery_source"] == "sso"


async def test_unmatched_event_is_recorded_but_creates_no_register_row() -> None:
    db = MagicMock()
    upsert_result = MagicMock()
    upsert_result.one.return_value = MagicMock(inserted=True)
    db.execute = AsyncMock(return_value=upsert_result)
    db.flush = AsyncMock()
    processor = SSOProbeProcessor(_matcher(None))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()) as reconcile:
        result = await processor.process(
            db=db, org_id=uuid.uuid4(), events=[_raw_event(app_name="Internal Payroll")]
        )

    # An unknown app is still evidence worth keeping — we just cannot say
    # what it is, so it must not enter the compliance register.
    assert result.unmatched == 1
    assert result.created == 1
    reconcile.assert_not_awaited()


async def test_repeated_grant_is_deduplicated_not_recreated() -> None:
    entry = _catalog_entry()
    db = _db(inserted=False, catalog_entry=entry)
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        result = await processor.process(db=db, org_id=uuid.uuid4(), events=[_raw_event()])

    assert result.deduplicated == 1
    assert result.created == 0


async def test_process_reports_every_event_it_saw() -> None:
    entry = _catalog_entry()
    db = MagicMock()
    upsert_result = MagicMock()
    upsert_result.one.return_value = MagicMock(inserted=True)
    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(side_effect=[upsert_result, lookup_result] * 3)
    db.flush = AsyncMock()
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        result = await processor.process(
            db=db,
            org_id=uuid.uuid4(),
            events=[
                _raw_event(user="ada@corp.com"),
                _raw_event(user="grace@corp.com"),
                _raw_event(user="alan@corp.com"),
            ],
        )

    assert result.processed == 3
    assert len(result.results) == 3


async def test_malformed_timestamp_does_not_abort_the_batch() -> None:
    entry = _catalog_entry()
    db = _db(catalog_entry=entry)
    bad = _raw_event()
    bad["timestamp"] = "whenever"
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        result = await processor.process(db=db, org_id=uuid.uuid4(), events=[bad])

    assert result.processed == 1


async def test_upsert_binds_the_org_and_marks_the_event_as_sso() -> None:
    org_id = uuid.uuid4()
    entry = _catalog_entry()
    db = _db(catalog_entry=entry)
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        await processor.process(db=db, org_id=org_id, events=[_raw_event()])

    params = db.execute.await_args_list[0].args[1]
    assert params["org_id"] == org_id
    assert params["probe_type"] == "sso"
    assert params["catalog_entry_id"] == entry.id


async def test_seen_at_passed_to_reconcile_is_timezone_aware() -> None:
    entry = _catalog_entry()
    db = _db(catalog_entry=entry)
    processor = SSOProbeProcessor(_matcher(entry.id))

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()) as reconcile:
        await processor.process(db=db, org_id=uuid.uuid4(), events=[_raw_event()])

    seen_at = reconcile.await_args.kwargs["seen_at"]
    # last_seen_at is timestamptz; a naive datetime here silently shifts
    # by the server's offset on write.
    assert seen_at.tzinfo is not None
    assert seen_at == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
