"""Unit tests for the SSO app matcher."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.discovery.sso_matcher import SSOAppMatcher


def _db_returning(rows: list[tuple]) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


async def test_create_indexes_oauth_app_ids_from_catalog() -> None:
    entry_id = uuid.uuid4()
    db = _db_returning([(entry_id, "Notion AI", ["0oa1notion"])])

    matcher = await SSOAppMatcher.create(db)

    assert matcher.match(oauth_app_id="0oa1notion", app_name="irrelevant") == entry_id


async def test_match_falls_back_to_service_name_when_oauth_id_unknown() -> None:
    entry_id = uuid.uuid4()
    db = _db_returning([(entry_id, "Notion AI", ["0oa1notion"])])

    matcher = await SSOAppMatcher.create(db)

    assert matcher.match(oauth_app_id="0oaUNSEEN", app_name="Notion AI") == entry_id


async def test_match_by_name_is_case_and_whitespace_insensitive() -> None:
    entry_id = uuid.uuid4()
    db = _db_returning([(entry_id, "Notion AI", [])])

    matcher = await SSOAppMatcher.create(db)

    assert matcher.match(oauth_app_id=None, app_name="  nOtIoN aI  ") == entry_id


async def test_match_returns_none_for_unknown_app() -> None:
    db = _db_returning([(uuid.uuid4(), "Notion AI", ["0oa1notion"])])

    matcher = await SSOAppMatcher.create(db)

    assert matcher.match(oauth_app_id="0oaOTHER", app_name="Internal Payroll Tool") is None


async def test_oauth_id_wins_over_conflicting_name_match() -> None:
    notion_id, jasper_id = uuid.uuid4(), uuid.uuid4()
    db = _db_returning(
        [
            (notion_id, "Notion AI", ["0oa1notion"]),
            (jasper_id, "Jasper", ["0oa2jasper"]),
        ]
    )

    matcher = await SSOAppMatcher.create(db)

    # Okta label says Jasper, but the OAuth client id is Notion's. The id
    # is the stronger signal — labels are free text an admin can rename.
    assert matcher.match(oauth_app_id="0oa1notion", app_name="Jasper") == notion_id


async def test_create_tolerates_null_oauth_app_ids() -> None:
    entry_id = uuid.uuid4()
    db = _db_returning([(entry_id, "Notion AI", None)])

    matcher = await SSOAppMatcher.create(db)

    assert matcher.match(oauth_app_id=None, app_name="Notion AI") == entry_id
