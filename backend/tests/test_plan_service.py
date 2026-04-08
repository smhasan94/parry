"""Unit tests for plan_service limit table + feature gate.

DB-backed enforcement (check_agent_limit, check_event_quota,
count_events_since) is exercised in e2e tests; here we lock down
the limit table, require_feature behaviour, and resolve_plan_from_
subscription which is a pure dict walk.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.db.models import Org, Plan
from app.services import plan_service
from app.services.billing_service import (
    resolve_plan_from_subscription,
)


def _make_org(plan: Plan = Plan.FREE) -> Org:
    return Org(
        id=uuid.uuid4(),
        name="Test",
        clerk_org_id=f"c_{uuid.uuid4().hex[:8]}",
        is_active=True,
        plan=plan,
    )


# ── limit table ──────────────────────────────────────────────────────


def test_every_plan_has_all_limit_keys() -> None:
    required = {
        "max_agents",
        "max_events_per_month",
        "retention_days",
        "custom_rules",
        "compliance_export",
    }
    for plan, limits in plan_service.PLAN_LIMITS.items():
        assert required.issubset(limits.keys()), f"{plan} missing keys"


def test_free_plan_denies_premium_features() -> None:
    limits = plan_service.PLAN_LIMITS[Plan.FREE]
    assert limits["max_agents"] == 1
    assert limits["max_events_per_month"] == 10_000
    assert limits["custom_rules"] is False
    assert limits["compliance_export"] is False


def test_enterprise_plan_is_unlimited() -> None:
    limits = plan_service.PLAN_LIMITS[Plan.ENTERPRISE]
    assert limits["max_agents"] is None
    assert limits["max_events_per_month"] is None
    assert limits["retention_days"] is None
    assert limits["custom_rules"] is True
    assert limits["compliance_export"] is True


def test_get_limits_returns_a_copy() -> None:
    limits = plan_service.get_limits(Plan.FREE)
    limits["max_agents"] = 999
    # Mutation should not leak back into the shared table.
    assert plan_service.PLAN_LIMITS[Plan.FREE]["max_agents"] == 1


# ── require_feature ──────────────────────────────────────────────────


def test_require_feature_allows_enabled_feature() -> None:
    plan_service.require_feature(_make_org(Plan.GROWTH), "custom_rules")
    plan_service.require_feature(_make_org(Plan.PRO), "compliance_export")


def test_require_feature_raises_402_on_free() -> None:
    for feature in ("custom_rules", "compliance_export"):
        with pytest.raises(HTTPException) as exc:
            plan_service.require_feature(_make_org(Plan.FREE), feature)
        assert exc.value.status_code == 402
        assert exc.value.headers == {"X-Upgrade-Required": "true"}
        assert feature in exc.value.detail


def test_require_feature_unknown_feature_is_denied_by_default() -> None:
    with pytest.raises(HTTPException) as exc:
        plan_service.require_feature(_make_org(Plan.ENTERPRISE), "not_a_real_feature")
    assert exc.value.status_code == 402


# ── Stripe price -> plan resolver ────────────────────────────────────


def test_resolve_plan_from_subscription_maps_growth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_123")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_456")
    sub = {"items": {"data": [{"price": {"id": "price_growth_123"}}]}}
    assert resolve_plan_from_subscription(sub) == Plan.GROWTH


def test_resolve_plan_from_subscription_maps_pro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_123")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_456")
    sub = {"items": {"data": [{"price": {"id": "price_pro_456"}}]}}
    assert resolve_plan_from_subscription(sub) == Plan.PRO


def test_resolve_plan_from_subscription_unknown_price_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "stripe_price_id_growth", "price_growth_123")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_456")
    sub = {"items": {"data": [{"price": {"id": "price_unknown_xyz"}}]}}
    assert resolve_plan_from_subscription(sub) == Plan.FREE


def test_resolve_plan_from_subscription_empty_items_is_free() -> None:
    assert resolve_plan_from_subscription({}) == Plan.FREE
    assert resolve_plan_from_subscription({"items": {"data": []}}) == Plan.FREE


# ── on-prem license override ────────────────────────────────────────


def test_effective_limits_uses_license_in_on_prem_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from app.core import on_prem
    from app.services.license_service import License

    lic = License(
        license_id="lic_1",
        customer_name="Acme",
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        max_agents=25,
        max_events_per_month=250_000,
        features=("custom_rules",),
        schema_version="1.0",
    )

    monkeypatch.setattr(on_prem, "_license", lic)
    monkeypatch.setattr(on_prem.settings, "on_prem_mode", True)

    try:
        org = _make_org(Plan.FREE)  # plan column should be ignored
        limits = plan_service._effective_limits(org)
        assert limits["max_agents"] == 25
        assert limits["max_events_per_month"] == 250_000
        assert limits["custom_rules"] is True
        assert limits["compliance_export"] is False
    finally:
        on_prem.reset_for_tests()


def test_effective_limits_fails_closed_when_license_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import on_prem

    monkeypatch.setattr(on_prem, "_license", None)
    monkeypatch.setattr(on_prem.settings, "on_prem_mode", True)

    try:
        org = _make_org(Plan.ENTERPRISE)  # wouldn't matter in on-prem
        limits = plan_service._effective_limits(org)
        # Fail closed: no license → no access, even if the org row
        # claimed Enterprise.
        assert limits["max_agents"] == 0
        assert limits["max_events_per_month"] == 0
        assert limits["custom_rules"] is False
    finally:
        on_prem.reset_for_tests()


def test_effective_limits_uses_plan_table_when_not_on_prem() -> None:
    org = _make_org(Plan.GROWTH)
    limits = plan_service._effective_limits(org)
    assert limits == plan_service.PLAN_LIMITS[Plan.GROWTH]
