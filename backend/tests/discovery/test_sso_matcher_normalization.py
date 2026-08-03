"""Normalized fallback matching for SSO app labels.

Admins rename apps, and only 13 of 200 catalog entries carry an OAuth
client id, so exact name matching misses real vendors. The fallback is
deliberately asymmetric.

Extra words in the *label* are fine — "Anthropic Claude" and "Perplexity
AI" name the same products the catalog calls "Claude" and "Perplexity".
Extra words in the *catalog name* are not. Matching an app labelled
"Figma" to a catalog entry called "Figma AI" would assert that the org
uses Figma's AI features, on the evidence of an SSO grant that says only
that they use Figma. In a compliance register a wrong row is worse than
a missing one, so that direction is refused.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.discovery.sso_matcher import SSOAppMatcher


def _matcher(entries: list[tuple[str, str, list[str]]]) -> SSOAppMatcher:
    """entries: (service_name, vendor, oauth_app_ids)"""
    rows = [(uuid.uuid4(), name, ids) for name, _vendor, ids in entries]
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db, {name: rid for rid, name, _ in rows}


async def _build(entries):
    db, ids = _matcher(entries)
    return await SSOAppMatcher.create(db), ids


CATALOG = [
    ("Claude", "Anthropic", []),
    ("ChatGPT", "OpenAI", ["0oa1chatgpt"]),
    ("Perplexity", "Perplexity", []),
    ("Figma AI", "Figma", []),
    ("Notion AI", "Notion", []),
    ("Greenhouse AI", "Greenhouse Software, Inc.", []),
    ("HireVue", "HireVue, Inc.", []),
]


async def test_oauth_id_still_takes_precedence() -> None:
    matcher, ids = await _build(CATALOG)

    assert matcher.match(oauth_app_id="0oa1chatgpt", app_name="Claude") == ids["ChatGPT"]


async def test_exact_name_still_matches() -> None:
    matcher, ids = await _build(CATALOG)

    assert matcher.match(oauth_app_id=None, app_name="HireVue") == ids["HireVue"]


async def test_a_vendor_prefixed_label_matches() -> None:
    matcher, ids = await _build(CATALOG)

    # Okta shows "Anthropic Claude"; the catalog calls it "Claude".
    assert matcher.match(oauth_app_id=None, app_name="Anthropic Claude") == ids["Claude"]


async def test_a_label_with_extra_qualifiers_matches() -> None:
    matcher, ids = await _build(CATALOG)

    assert matcher.match(oauth_app_id=None, app_name="OpenAI ChatGPT Enterprise") == ids["ChatGPT"]


async def test_a_label_with_a_trailing_ai_matches() -> None:
    matcher, ids = await _build(CATALOG)

    assert matcher.match(oauth_app_id=None, app_name="Perplexity AI") == ids["Perplexity"]


async def test_a_bare_vendor_label_does_not_match_an_ai_product() -> None:
    matcher, _ = await _build(CATALOG)

    # The grant says they use Figma. It does not say they use Figma AI.
    assert matcher.match(oauth_app_id=None, app_name="Figma") is None
    assert matcher.match(oauth_app_id=None, app_name="Notion") is None
    assert matcher.match(oauth_app_id=None, app_name="Greenhouse") is None


async def test_an_unrelated_app_does_not_match() -> None:
    matcher, _ = await _build(CATALOG)

    for label in ("Salesforce", "Workday", "1Password", "Okta Admin Console"):
        assert matcher.match(oauth_app_id=None, app_name=label) is None, label


async def test_an_ambiguous_label_is_refused() -> None:
    matcher, _ = await _build(
        [("Drift AI", "Drift", []), ("Drift", "Drift", [])],
    )

    # "Drift AI Assistant" contains both catalog names. Guessing between
    # them is worse than returning nothing.
    assert matcher.match(oauth_app_id=None, app_name="Drift AI Assistant") is None


async def test_an_empty_label_matches_nothing() -> None:
    matcher, _ = await _build(CATALOG)

    for label in ("", "   ", "!!!"):
        assert matcher.match(oauth_app_id=None, app_name=label) is None, repr(label)


async def test_punctuation_and_case_do_not_prevent_a_match() -> None:
    matcher, ids = await _build(CATALOG)

    assert matcher.match(oauth_app_id=None, app_name="  hirevue  ") == ids["HireVue"]
    assert matcher.match(oauth_app_id=None, app_name="HireVue!") == ids["HireVue"]


async def test_a_catalog_entry_named_only_of_noise_matches_nothing() -> None:
    # "Plus AI" reduces to nothing once noise words are ignored. If that
    # were allowed to match, it would match every app in the tenant.
    matcher, _ = await _build([("Plus AI", "Plus", [])])

    assert matcher.match(oauth_app_id=None, app_name="Salesforce") is None
    assert matcher.match(oauth_app_id=None, app_name="Workday") is None
