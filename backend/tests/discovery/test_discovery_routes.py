"""Unit tests for the discovery route handlers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import discovery
from app.core.dependencies import Actor
from app.db.models import Org
from app.discovery.sso_probe import ProcessingResult
from app.schemas.discovery import SSOIngestRequest, SSOSyncRequest
from app.services.discovery_service import ShadowSystem


def _org() -> Org:
    return Org(id=uuid.uuid4(), name="Acme", clerk_org_id="org_test", is_active=True)


def _db() -> MagicMock:
    """A session whose async surface is awaitable — the handlers write an
    audit entry, which flushes."""
    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _actor() -> Actor:
    return Actor(actor_type="user", actor_id="user_123", label="ada@corp.com")


def _shadow_system(name: str = "Notion AI", risk: str = "limited") -> ShadowSystem:
    return ShadowSystem(
        id=uuid.uuid4(),
        name=name,
        provider_name="Notion",
        risk_level="unclassified",
        proposed_risk_level=risk,
        proposed_reasoning="Default tier from the AI catalog.",
        pending_classification_id=uuid.uuid4(),
        discovery_source="sso",
        first_seen_at=datetime(2026, 1, 5, tzinfo=UTC),
        last_seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )


async def test_shadow_endpoint_returns_systems_and_summary() -> None:
    org = _org()
    systems = [_shadow_system("Notion AI"), _shadow_system("Jasper", risk="high")]

    with (
        patch.object(
            discovery.discovery_service, "list_shadow_systems", new=AsyncMock(return_value=systems)
        ),
        patch.object(
            discovery.discovery_service,
            "shadow_summary",
            new=AsyncMock(return_value={"total": 2, "by_risk_level": {"limited": 1, "high": 1}}),
        ),
    ):
        response = await discovery.list_shadow_ai(org_actor=(org, _actor()), db=_db(), limit=100)

    assert response.total == 2
    assert response.by_risk_level == {"limited": 1, "high": 1}
    assert [s.name for s in response.systems] == ["Notion AI", "Jasper"]
    assert response.systems[0].provider_name == "Notion"


async def test_shadow_endpoint_is_scoped_to_the_calling_org() -> None:
    org = _org()

    with (
        patch.object(
            discovery.discovery_service, "list_shadow_systems", new=AsyncMock(return_value=[])
        ) as list_call,
        patch.object(
            discovery.discovery_service,
            "shadow_summary",
            new=AsyncMock(return_value={"total": 0, "by_risk_level": {}}),
        ),
    ):
        await discovery.list_shadow_ai(org_actor=(org, _actor()), db=_db(), limit=50)

    assert list_call.await_args.kwargs["org_id"] == org.id


async def test_ingest_processes_supplied_events() -> None:
    org = _org()
    processor = MagicMock()
    processor.process = AsyncMock(
        return_value=ProcessingResult(processed=2, created=2, matched=1, unmatched=1)
    )

    with patch.object(discovery.SSOProbeProcessor, "create", new=AsyncMock(return_value=processor)):
        response = await discovery.ingest_sso_events(
            payload=SSOIngestRequest(events=[{"app_name": "Notion AI"}, {"app_name": "Jasper"}]),
            org_actor=(org, _actor()),
            db=_db(),
        )

    assert response.processed == 2
    assert response.matched == 1
    assert response.unmatched == 1
    assert processor.process.await_args.kwargs["org_id"] == org.id


async def test_ingest_rejects_an_empty_batch() -> None:
    with pytest.raises(HTTPException) as exc:
        await discovery.ingest_sso_events(
            payload=SSOIngestRequest(events=[]),
            org_actor=(_org(), _actor()),
            db=_db(),
        )

    assert exc.value.status_code == 400


async def test_sync_fetches_from_okta_then_processes() -> None:
    org = _org()
    processor = MagicMock()
    processor.process_events = AsyncMock(
        return_value=ProcessingResult(processed=1, created=1, matched=1)
    )
    okta_payload = [{"app": {"id": "0oa1", "label": "Notion AI", "status": "ACTIVE"}, "users": []}]

    with (
        patch.object(
            discovery, "fetch_okta_apps_and_users", new=AsyncMock(return_value=okta_payload)
        ) as fetch,
        patch.object(discovery.SSOProbeProcessor, "create", new=AsyncMock(return_value=processor)),
    ):
        response = await discovery.sync_okta(
            payload=SSOSyncRequest(okta_domain="acme.okta.com", api_token="secret-token"),
            org_actor=(org, _actor()),
            db=_db(),
        )

    assert fetch.await_args.kwargs["okta_domain"] == "acme.okta.com"
    assert response.processed == 1


async def test_sync_surfaces_okta_auth_failure_as_502_not_500() -> None:
    import httpx

    request = httpx.Request("GET", "https://acme.okta.com/api/v1/apps")
    error = httpx.HTTPStatusError(
        "401", request=request, response=httpx.Response(401, request=request)
    )

    with (
        patch.object(discovery, "fetch_okta_apps_and_users", new=AsyncMock(side_effect=error)),
        pytest.raises(HTTPException) as exc,
    ):
        await discovery.sync_okta(
            payload=SSOSyncRequest(okta_domain="acme.okta.com", api_token="bad"),
            org_actor=(_org(), _actor()),
            db=_db(),
        )

    # An upstream credential problem is not a Parry bug — surfacing it as
    # 500 would page the wrong team.
    assert exc.value.status_code == 502


async def test_sync_never_echoes_the_api_token() -> None:
    processor = MagicMock()
    processor.process_events = AsyncMock(return_value=ProcessingResult(processed=0))

    with (
        patch.object(discovery, "fetch_okta_apps_and_users", new=AsyncMock(return_value=[])),
        patch.object(discovery.SSOProbeProcessor, "create", new=AsyncMock(return_value=processor)),
    ):
        response = await discovery.sync_okta(
            payload=SSOSyncRequest(okta_domain="acme.okta.com", api_token="super-secret"),
            org_actor=(_org(), _actor()),
            db=_db(),
        )

    assert "super-secret" not in response.model_dump_json()


async def test_sync_rejects_a_domain_outside_the_okta_allowlist() -> None:
    from app.discovery.okta import OktaDomainError

    with (
        patch.object(
            discovery,
            "fetch_okta_apps_and_users",
            new=AsyncMock(side_effect=OktaDomainError("not an Okta tenant")),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await discovery.sync_okta(
            payload=SSOSyncRequest.model_construct(okta_domain="169.254.169.254", api_token="tok"),
            org_actor=(_org(), _actor()),
            db=_db(),
        )

    # Caller-supplied garbage is a 400, not a 502 — the upstream is fine,
    # the request is not.
    assert exc.value.status_code == 400


def test_schema_rejects_a_non_okta_domain_before_the_handler_runs() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SSOSyncRequest(okta_domain="169.254.169.254", api_token="tok")


def test_schema_accepts_a_real_okta_tenant() -> None:
    assert SSOSyncRequest(okta_domain="acme.okta.com", api_token="tok").okta_domain == (
        "acme.okta.com"
    )
