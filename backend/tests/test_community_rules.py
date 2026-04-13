"""Unit tests for the community rules service."""


import pytest

from app.services.community_rules_service import (
    MAX_RULES_PER_PACK,
    VALID_CATEGORIES,
    _slugify,
    _validate_rules,
)


def test_slugify_basic():
    assert _slugify("Healthcare PII Patterns") == "healthcare-pii-patterns"


def test_slugify_special_chars():
    assert _slugify("Finance & Banking (v2)") == "finance-banking-v2"


def test_slugify_long_name():
    slug = _slugify("a" * 200)
    assert len(slug) <= 100


def test_slugify_empty():
    assert _slugify("") == ""


def test_validate_rules_valid():
    rules = [
        {"name": "SSN detector", "pattern": r"\d{3}-\d{2}-\d{4}", "target": "response", "severity": "high"},
        {"name": "API key leak", "pattern": r"sk-[a-z0-9]{32}", "target": "both"},
    ]
    _validate_rules(rules)  # should not raise


def test_validate_rules_empty_list():
    with pytest.raises(ValueError, match="at least one rule"):
        _validate_rules([])


def test_validate_rules_too_many():
    rules = [{"name": f"rule-{i}", "pattern": r"test"} for i in range(MAX_RULES_PER_PACK + 1)]
    with pytest.raises(ValueError, match="at most"):
        _validate_rules(rules)


def test_validate_rules_missing_name():
    with pytest.raises(ValueError, match="name and pattern"):
        _validate_rules([{"name": "", "pattern": r"test"}])


def test_validate_rules_missing_pattern():
    with pytest.raises(ValueError, match="name and pattern"):
        _validate_rules([{"name": "test", "pattern": ""}])


def test_validate_rules_invalid_regex():
    with pytest.raises(ValueError, match="invalid regex"):
        _validate_rules([{"name": "bad", "pattern": r"[invalid"}])


def test_validate_rules_invalid_target():
    with pytest.raises(ValueError, match="target"):
        _validate_rules([{"name": "test", "pattern": r"test", "target": "invalid"}])


def test_validate_rules_invalid_severity():
    with pytest.raises(ValueError, match="severity"):
        _validate_rules([{"name": "test", "pattern": r"test", "severity": "ultra"}])


def test_valid_categories_not_empty():
    assert len(VALID_CATEGORIES) > 0
    assert "healthcare" in VALID_CATEGORIES
    assert "finance" in VALID_CATEGORIES
    assert "pii" in VALID_CATEGORIES


def test_max_rules_per_pack_reasonable():
    assert 10 <= MAX_RULES_PER_PACK <= 100
