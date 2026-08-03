"""Unit tests for catalog seed parsing and validation."""

from __future__ import annotations

import pytest

from app.discovery.catalog_seed import CatalogSeedError, parse_catalog_entries


def _entry(**overrides) -> dict:
    base = {
        "service_name": "Notion AI",
        "vendor": "Notion",
        "category": "productivity",
        "domains": ["notion.so", "notion.com"],
        "oauth_app_ids": ["0oa1notion"],
        "foundation_models": ["gpt-4o"],
        "trains_on_user_data": False,
        "data_retention_days": 30,
        "has_enterprise_dpa": True,
        "soc2_certified": True,
        "default_risk_tier": "limited",
        "risk_tier_rationale": "Generative assistant over staff content.",
        "privacy_policy_url": None,
        "tos_url": None,
    }
    base.update(overrides)
    return base


def test_parse_returns_entry_with_its_domains() -> None:
    parsed = parse_catalog_entries([_entry()])

    assert len(parsed) == 1
    entry, domains = parsed[0]
    assert entry["service_name"] == "Notion AI"
    assert entry["vendor"] == "Notion"
    assert domains == ["notion.so", "notion.com"]


def test_parse_lowercases_and_dedupes_domains() -> None:
    _, domains = parse_catalog_entries([_entry(domains=["Notion.SO", "notion.so", "NOTION.com"])])[
        0
    ]

    assert domains == ["notion.so", "notion.com"]


def test_parse_rejects_an_entry_missing_a_required_field() -> None:
    broken = _entry()
    del broken["vendor"]

    with pytest.raises(CatalogSeedError, match="vendor"):
        parse_catalog_entries([broken])


def test_parse_rejects_an_unknown_risk_tier() -> None:
    with pytest.raises(CatalogSeedError, match="critical"):
        parse_catalog_entries([_entry(default_risk_tier="critical")])


def test_parse_allows_a_null_risk_tier() -> None:
    entry, _ = parse_catalog_entries([_entry(default_risk_tier=None)])[0]

    assert entry["default_risk_tier"] is None


def test_parse_rejects_the_same_domain_claimed_by_two_vendors() -> None:
    # catalog_domains.domain is globally unique — a collision here would
    # fail at insert time with an opaque constraint error, so catch it in
    # the loader where the message can name both vendors.
    entries = [
        _entry(service_name="Notion AI", vendor="Notion", domains=["shared.ai"]),
        _entry(service_name="Jasper", vendor="Jasper", domains=["shared.ai"]),
    ]

    with pytest.raises(CatalogSeedError, match="shared.ai"):
        parse_catalog_entries(entries)


def test_parse_rejects_duplicate_vendor_service_pairs() -> None:
    entries = [_entry(domains=["a.com"]), _entry(domains=["b.com"])]

    with pytest.raises(CatalogSeedError, match="Notion AI"):
        parse_catalog_entries(entries)


def test_parse_defaults_absent_optional_lists_to_empty() -> None:
    minimal = {
        "service_name": "Tiny AI",
        "vendor": "Tiny",
        "category": "misc",
        "domains": ["tiny.ai"],
    }

    entry, _ = parse_catalog_entries([minimal])[0]

    assert entry["oauth_app_ids"] == []
    assert entry["foundation_models"] == []


def test_parse_rejects_an_entry_with_no_domains() -> None:
    with pytest.raises(CatalogSeedError, match="domains"):
        parse_catalog_entries([_entry(domains=[])])


def test_real_catalog_file_parses() -> None:
    from app.discovery.catalog_seed import load_catalog_file

    parsed = parse_catalog_entries(load_catalog_file())

    assert len(parsed) >= 100
    assert all(domains for _, domains in parsed)
