"""The seam between parse_okta_response and the probe processor.

Both halves passed their own unit tests while the join between them lost
every field: NormalizedSSOEvent.raw is the *original Okta item*, so
feeding it back through the dict normalizer produced app_name="Unknown"
for every app. Nothing matched the catalog and every event collapsed onto
one dedup key. These tests exercise the two together.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import AICatalogEntry
from app.discovery.okta import parse_okta_response
from app.discovery.sso_probe import SSOProbeProcessor


def _okta_payload() -> list[dict]:
    return [
        {
            "app": {
                "id": "0oa1notion",
                "label": "Notion AI",
                "status": "ACTIVE",
                "created": "2026-01-15T10:00:00.000Z",
            },
            "users": [
                {"profile": {"login": "ada@corp.com"}},
                {"profile": {"login": "grace@corp.com"}},
            ],
        }
    ]


def _entry() -> AICatalogEntry:
    return AICatalogEntry(
        id=uuid.uuid4(),
        service_name="Notion AI",
        vendor="Notion",
        category="productivity",
        default_risk_tier="limited",
    )


def _db(entry: AICatalogEntry) -> MagicMock:
    db = MagicMock()
    upsert = MagicMock()
    upsert.one.return_value = MagicMock(inserted=True)
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = entry
    db.execute = AsyncMock(side_effect=[upsert, lookup] * 8)
    db.flush = AsyncMock()
    return db


async def test_okta_app_identity_survives_the_handoff_to_the_processor() -> None:
    entry = _entry()
    matcher = MagicMock()
    matcher.match.return_value = entry.id
    processor = SSOProbeProcessor(matcher)

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        await processor.process_events(
            db=_db(entry), org_id=uuid.uuid4(), events=parse_okta_response(_okta_payload())
        )

    # The matcher must see the real Okta label and client id, not the
    # placeholders that a lossy round-trip produces.
    names = {c.kwargs["app_name"] for c in matcher.match.call_args_list}
    ids = {c.kwargs["oauth_app_id"] for c in matcher.match.call_args_list}
    assert names == {"Notion AI"}
    assert ids == {"0oa1notion"}


async def test_two_users_of_one_app_stay_distinct_through_the_pipeline() -> None:
    entry = _entry()
    matcher = MagicMock()
    matcher.match.return_value = entry.id
    processor = SSOProbeProcessor(matcher)

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        result = await processor.process_events(
            db=_db(entry), org_id=uuid.uuid4(), events=parse_okta_response(_okta_payload())
        )

    # Distinct users must not collapse onto one dedup key.
    assert result.processed == 2
    assert result.created == 2
    assert result.deduplicated == 0
    assert result.matched == 2


async def test_raw_payload_still_stores_the_original_okta_item() -> None:
    entry = _entry()
    matcher = MagicMock()
    matcher.match.return_value = entry.id
    db = _db(entry)
    processor = SSOProbeProcessor(matcher)

    with patch("app.discovery.sso_probe.reconcile_ai_system", new=AsyncMock()):
        await processor.process_events(
            db=db, org_id=uuid.uuid4(), events=parse_okta_response(_okta_payload())
        )

    # Forensics needs what Okta actually said, not our projection of it.
    payload = db.execute.await_args_list[0].args[1]["raw_payload"]
    assert '"label": "Notion AI"' in payload
    assert '"users"' in payload
