"""Tests for detection_service._merge_policies()."""

import uuid

from app.db.models import Policy
from app.services.detection_service import _merge_policies


def _make_policy(**kwargs) -> Policy:
    defaults = {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "name": "test",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Policy(**defaults)


class TestMergePolicies:
    def test_empty_list(self) -> None:
        result = _merge_policies([])
        assert result["allowed_tools"] == []
        assert result["blocked_tools"] == []
        assert result["forbidden_patterns"] == []

    def test_single_policy(self) -> None:
        p = _make_policy(
            allowed_tools=["search", "read"],
            blocked_tools=["exec_code"],
            max_token_budget=50000,
        )
        result = _merge_policies([p])
        assert set(result["allowed_tools"]) == {"search", "read"}
        assert result["blocked_tools"] == ["exec_code"]
        assert result["max_token_budget"] == 50000

    def test_merges_tools_from_multiple_policies(self) -> None:
        p1 = _make_policy(allowed_tools=["search"], blocked_tools=["shell"])
        p2 = _make_policy(allowed_tools=["read_file"], blocked_tools=["exec_code"])
        result = _merge_policies([p1, p2])
        assert set(result["allowed_tools"]) == {"search", "read_file"}
        assert set(result["blocked_tools"]) == {"shell", "exec_code"}

    def test_deduplicates_tools(self) -> None:
        p1 = _make_policy(allowed_tools=["search", "read"])
        p2 = _make_policy(allowed_tools=["search", "write"])
        result = _merge_policies([p1, p2])
        assert sorted(result["allowed_tools"]) == sorted(list(set(["search", "read", "write"])))

    def test_takes_minimum_token_budget(self) -> None:
        p1 = _make_policy(max_token_budget=100000)
        p2 = _make_policy(max_token_budget=50000)
        p3 = _make_policy(max_token_budget=200000)
        result = _merge_policies([p1, p2, p3])
        assert result["max_token_budget"] == 50000

    def test_none_fields_ignored(self) -> None:
        p = _make_policy(
            allowed_tools=None,
            blocked_tools=None,
            allowed_domains=None,
            blocked_domains=None,
            forbidden_patterns=None,
            max_token_budget=None,
        )
        result = _merge_policies([p])
        assert result["allowed_tools"] == []
        assert result["blocked_tools"] == []
        assert "max_token_budget" not in result

    def test_forbidden_patterns_merged(self) -> None:
        p1 = _make_policy(forbidden_patterns=["password", "secret"])
        p2 = _make_policy(forbidden_patterns=["api_key"])
        result = _merge_policies([p1, p2])
        assert set(result["forbidden_patterns"]) == {"password", "secret", "api_key"}
