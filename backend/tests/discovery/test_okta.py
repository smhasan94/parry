"""Unit tests for Okta payload normalization and the dedup key."""

from __future__ import annotations

from datetime import UTC, datetime

from app.discovery.events import NormalizedSSOEvent
from app.discovery.okta import parse_okta_response


def _app(app_id: str = "0oa1notion", label: str = "Notion AI", status: str = "ACTIVE") -> dict:
    return {"id": app_id, "label": label, "status": status, "created": "2026-01-15T10:00:00.000Z"}


def test_parse_emits_one_event_per_assigned_user() -> None:
    payload = [
        {
            "app": _app(),
            "users": [
                {"profile": {"login": "ada@corp.com"}},
                {"profile": {"login": "grace@corp.com"}},
            ],
        }
    ]

    events = parse_okta_response(payload)

    assert [e.user_identifier for e in events] == ["ada@corp.com", "grace@corp.com"]
    assert all(e.app_name == "Notion AI" for e in events)
    assert all(e.oauth_app_id == "0oa1notion" for e in events)


def test_parse_emits_one_event_for_app_with_no_assigned_users() -> None:
    events = parse_okta_response([{"app": _app(), "users": []}])

    assert len(events) == 1
    assert events[0].user_identifier is None


def test_parse_maps_okta_status_to_internal_vocabulary() -> None:
    events = parse_okta_response([{"app": _app(status="INACTIVE"), "users": []}])

    assert events[0].status == "inactive"


def test_parse_falls_back_to_unknown_for_unrecognized_status() -> None:
    events = parse_okta_response([{"app": _app(status="DELETED"), "users": []}])

    assert events[0].status == "unknown"


def test_parse_reads_created_timestamp_as_utc() -> None:
    events = parse_okta_response([{"app": _app(), "users": []}])

    assert events[0].timestamp == datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_parse_survives_malformed_created_timestamp() -> None:
    app = _app()
    app["created"] = "not-a-date"

    events = parse_okta_response([{"app": app, "users": []}])

    assert events[0].timestamp.tzinfo is not None


def test_parse_skips_entries_missing_the_app_object() -> None:
    events = parse_okta_response([{"users": []}, {"app": _app(), "users": []}])

    assert len(events) == 1


def test_dedup_key_is_stable_across_syncs() -> None:
    def make(ts: datetime) -> NormalizedSSOEvent:
        return NormalizedSSOEvent(
            timestamp=ts,
            provider="okta",
            oauth_app_id="0oa1notion",
            app_name="Notion AI",
            user_identifier="ada@corp.com",
            grant_type="admin_assigned",
            status="active",
            raw={},
        )

    # Same grant seen on two different days must collapse to one row —
    # an OAuth grant is persistent, not an event in time.
    assert (
        make(datetime(2026, 1, 15, tzinfo=UTC)).dedup_key()
        == make(datetime(2026, 3, 2, tzinfo=UTC)).dedup_key()
    )


def test_dedup_key_separates_distinct_users_of_the_same_app() -> None:
    def make(login: str) -> NormalizedSSOEvent:
        return NormalizedSSOEvent(
            timestamp=datetime(2026, 1, 15, tzinfo=UTC),
            provider="okta",
            oauth_app_id="0oa1notion",
            app_name="Notion AI",
            user_identifier=login,
            grant_type="admin_assigned",
            status="active",
            raw={},
        )

    assert make("ada@corp.com").dedup_key() != make("grace@corp.com").dedup_key()
