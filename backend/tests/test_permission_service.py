"""Tests for permission_service — pure evaluation logic, no DB required.

Covers all combinations of mode × default_action × allowlist/blocklist,
plus resolution order and edge cases.
"""

import uuid

from app.db.models import AgentPermission
from app.services.permission_service import PermissionResult, evaluate_permission


def _make_perm(
    mode: str = "enforcing",
    default_action: str = "allow",
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
) -> AgentPermission:
    return AgentPermission(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        mode=mode,
        default_action=default_action,
        allowed_tools=allowed_tools or [],
        blocked_tools=blocked_tools or [],
    )


AGENT_ID = str(uuid.uuid4())


# ── Disabled mode ───────────────────────────────────────────────


class TestDisabledMode:
    def test_disabled_allows_any_tool(self) -> None:
        perm = _make_perm(mode="disabled")
        result = evaluate_permission(perm, "any_tool", AGENT_ID)
        assert result.allowed is True
        assert result.mode == "disabled"

    def test_disabled_ignores_blocklist(self) -> None:
        perm = _make_perm(mode="disabled", blocked_tools=["secret_tool"])
        result = evaluate_permission(perm, "secret_tool", AGENT_ID)
        assert result.allowed is True

    def test_disabled_ignores_deny_default(self) -> None:
        perm = _make_perm(mode="disabled", default_action="deny")
        result = evaluate_permission(perm, "any_tool", AGENT_ID)
        assert result.allowed is True


# ── Allow-by-default (blocklist mode) ──────────────────────────


class TestAllowByDefault:
    def test_unlisted_tool_allowed(self) -> None:
        perm = _make_perm(default_action="allow")
        result = evaluate_permission(perm, "unknown_tool", AGENT_ID)
        assert result.allowed is True

    def test_blocked_tool_denied(self) -> None:
        perm = _make_perm(default_action="allow", blocked_tools=["dangerous_tool"])
        result = evaluate_permission(perm, "dangerous_tool", AGENT_ID)
        assert result.allowed is False
        assert "explicitly blocked" in result.reason

    def test_allowed_tool_explicit(self) -> None:
        perm = _make_perm(
            default_action="allow",
            allowed_tools=["safe_tool"],
            blocked_tools=["dangerous_tool"],
        )
        result = evaluate_permission(perm, "safe_tool", AGENT_ID)
        assert result.allowed is True
        assert "explicitly allowed" in result.reason

    def test_blocklist_case_insensitive(self) -> None:
        perm = _make_perm(default_action="allow", blocked_tools=["DangerousTool"])
        result = evaluate_permission(perm, "dangeroustool", AGENT_ID)
        assert result.allowed is False


# ── Deny-by-default (allowlist mode) ──────────────────────────


class TestDenyByDefault:
    def test_unlisted_tool_denied(self) -> None:
        perm = _make_perm(
            default_action="deny", allowed_tools=["search_kb"]
        )
        result = evaluate_permission(perm, "delete_account", AGENT_ID)
        assert result.allowed is False
        assert "not in allowlist" in result.reason

    def test_allowed_tool_passes(self) -> None:
        perm = _make_perm(
            default_action="deny", allowed_tools=["search_kb", "create_ticket"]
        )
        result = evaluate_permission(perm, "search_kb", AGENT_ID)
        assert result.allowed is True

    def test_blocked_tool_denied_even_if_in_allowlist(self) -> None:
        """Explicit blocklist wins over allowlist."""
        perm = _make_perm(
            default_action="deny",
            allowed_tools=["search_kb", "admin_tool"],
            blocked_tools=["admin_tool"],
        )
        result = evaluate_permission(perm, "admin_tool", AGENT_ID)
        assert result.allowed is False
        assert "explicitly blocked" in result.reason

    def test_allowlist_case_insensitive(self) -> None:
        perm = _make_perm(
            default_action="deny", allowed_tools=["SearchKB"]
        )
        result = evaluate_permission(perm, "searchkb", AGENT_ID)
        assert result.allowed is True


# ── Dry run mode ────────────────────────────────────────────────


class TestDryRunMode:
    def test_dry_run_denied_has_correct_mode(self) -> None:
        perm = _make_perm(
            mode="dry_run", default_action="deny", allowed_tools=["search_kb"]
        )
        result = evaluate_permission(perm, "delete_all", AGENT_ID)
        assert result.allowed is False
        assert result.mode == "dry_run"

    def test_dry_run_allowed_has_correct_mode(self) -> None:
        perm = _make_perm(
            mode="dry_run", default_action="deny", allowed_tools=["search_kb"]
        )
        result = evaluate_permission(perm, "search_kb", AGENT_ID)
        assert result.allowed is True
        assert result.mode == "dry_run"


# ── Edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_lists_allow_by_default(self) -> None:
        perm = _make_perm(default_action="allow", allowed_tools=[], blocked_tools=[])
        result = evaluate_permission(perm, "any_tool", AGENT_ID)
        assert result.allowed is True

    def test_tool_name_with_special_chars(self) -> None:
        perm = _make_perm(
            default_action="deny",
            allowed_tools=["get-weather.v2", "search_kb_v3"],
        )
        result = evaluate_permission(perm, "get-weather.v2", AGENT_ID)
        assert result.allowed is True

    def test_result_includes_tool_name(self) -> None:
        perm = _make_perm(default_action="allow")
        result = evaluate_permission(perm, "my_tool", AGENT_ID)
        assert result.tool_name == "my_tool"

    def test_result_includes_agent_id(self) -> None:
        perm = _make_perm(default_action="allow")
        result = evaluate_permission(perm, "my_tool", AGENT_ID)
        assert result.agent_id == AGENT_ID


# ── PermissionResult dataclass ──────────────────────────────────


class TestPermissionResult:
    def test_frozen(self) -> None:
        r = PermissionResult(
            allowed=True,
            mode="enforcing",
            reason="test",
            tool_name="t",
            agent_id="a",
            source="agent",
        )
        try:
            r.allowed = False  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass

    def test_source_agent(self) -> None:
        perm = _make_perm(default_action="allow")
        result = evaluate_permission(perm, "tool", AGENT_ID)
        assert result.source == "agent"


# ── Model construction ──────────────────────────────────────────


class TestAgentPermissionModel:
    def test_construction_with_explicit_defaults(self) -> None:
        """Python defaults only apply via DB flush; test explicit construction."""
        perm = AgentPermission(
            org_id=uuid.uuid4(),
            mode="disabled",
            default_action="allow",
            allowed_tools=[],
            blocked_tools=[],
        )
        assert perm.mode == "disabled"
        assert perm.default_action == "allow"
        assert perm.allowed_tools == []
        assert perm.blocked_tools == []
        assert perm.agent_id is None

    def test_construction_full(self) -> None:
        org_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        perm = AgentPermission(
            org_id=org_id,
            agent_id=agent_id,
            mode="enforcing",
            default_action="deny",
            allowed_tools=["search_kb", "create_ticket"],
            blocked_tools=["delete_account"],
        )
        assert perm.org_id == org_id
        assert perm.agent_id == agent_id
        assert perm.mode == "enforcing"
        assert perm.default_action == "deny"
        assert len(perm.allowed_tools) == 2
        assert len(perm.blocked_tools) == 1


# ── Feature gate ────────────────────────────────────────────────


class TestPermissionFeatureGate:
    def test_growth_has_permissions(self) -> None:
        from app.db.models import Plan
        from app.services.plan_service import PLAN_LIMITS

        assert PLAN_LIMITS[Plan.GROWTH]["agent_permissions"] is True

    def test_free_lacks_permissions(self) -> None:
        from app.db.models import Plan
        from app.services.plan_service import PLAN_LIMITS

        assert PLAN_LIMITS[Plan.FREE]["agent_permissions"] is False
