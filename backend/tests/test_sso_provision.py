"""Tests for SSO provisioning and session creation — pure logic + model tests.

No WorkOS or Clerk API calls — just schema validation, model construction,
and SSO profile dataclass behavior.
"""

import uuid

from app.api.v1.sso import (
    CallbackResponse,
    LoginRequest,
    ProvisionSSORequest,
    SessionRequest,
    SessionResponse,
    SSOStatusResponse,
)
from app.db.models import Org
from app.services.sso_service import SSOProfile


class TestSSOSchemas:
    """Validate the new Pydantic schemas parse correctly."""

    def test_session_request_full(self) -> None:
        req = SessionRequest(
            workos_user_id="user_01abc",
            email="alice@acme.com",
            org_id=str(uuid.uuid4()),
            first_name="Alice",
            last_name="Smith",
        )
        assert req.email == "alice@acme.com"
        assert req.first_name == "Alice"

    def test_session_request_minimal(self) -> None:
        req = SessionRequest(
            workos_user_id="user_01abc",
            email="alice@acme.com",
            org_id=str(uuid.uuid4()),
        )
        assert req.first_name is None
        assert req.last_name is None

    def test_session_response(self) -> None:
        resp = SessionResponse(ticket="tok_abc123")
        assert resp.ticket == "tok_abc123"

    def test_provision_request_set(self) -> None:
        req = ProvisionSSORequest(workos_organization_id="org_01def")
        assert req.workos_organization_id == "org_01def"

    def test_provision_request_clear(self) -> None:
        req = ProvisionSSORequest(workos_organization_id=None)
        assert req.workos_organization_id is None

    def test_provision_request_default_none(self) -> None:
        req = ProvisionSSORequest()
        assert req.workos_organization_id is None

    def test_sso_status_response_enabled(self) -> None:
        resp = SSOStatusResponse(
            enabled=True,
            configured_on_backend=True,
            workos_organization_id="org_01def",
        )
        assert resp.enabled is True

    def test_sso_status_response_disabled(self) -> None:
        resp = SSOStatusResponse(
            enabled=False,
            configured_on_backend=True,
            workos_organization_id=None,
        )
        assert resp.enabled is False

    def test_login_request_with_slug(self) -> None:
        req = LoginRequest(org_slug="acme-corp")
        assert req.org_slug == "acme-corp"
        assert req.workos_organization_id is None

    def test_login_request_with_workos_id(self) -> None:
        req = LoginRequest(workos_organization_id="org_01abc")
        assert req.workos_organization_id == "org_01abc"

    def test_callback_response(self) -> None:
        resp = CallbackResponse(
            org_id=str(uuid.uuid4()),
            org_name="Acme Corp",
            workos_user_id="user_01abc",
            workos_organization_id="org_01def",
            email="alice@acme.com",
            display_name="Alice Smith",
        )
        assert resp.email == "alice@acme.com"
        assert resp.display_name == "Alice Smith"


class TestSSOProfileDataclass:
    def test_display_name_full(self) -> None:
        p = SSOProfile(
            workos_user_id="u1",
            workos_organization_id="o1",
            email="alice@acme.com",
            first_name="Alice",
            last_name="Smith",
        )
        assert p.display_name == "Alice Smith"

    def test_display_name_first_only(self) -> None:
        p = SSOProfile(
            workos_user_id="u1",
            workos_organization_id="o1",
            email="alice@acme.com",
            first_name="Alice",
            last_name=None,
        )
        assert p.display_name == "Alice"

    def test_display_name_falls_back_to_email(self) -> None:
        p = SSOProfile(
            workos_user_id="u1",
            workos_organization_id="o1",
            email="alice@acme.com",
            first_name=None,
            last_name=None,
        )
        assert p.display_name == "alice@acme.com"

    def test_frozen(self) -> None:
        p = SSOProfile(
            workos_user_id="u1",
            workos_organization_id="o1",
            email="alice@acme.com",
            first_name=None,
            last_name=None,
        )
        try:
            p.email = "changed@acme.com"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestOrgWorkOSField:
    def test_org_workos_id_default_none(self) -> None:
        org = Org(
            name="Test",
            clerk_org_id="org_test",
        )
        assert org.workos_organization_id is None

    def test_org_workos_id_set(self) -> None:
        org = Org(
            name="Test",
            clerk_org_id="org_test",
            workos_organization_id="org_01workos",
        )
        assert org.workos_organization_id == "org_01workos"

    def test_org_workos_id_cleared(self) -> None:
        org = Org(
            name="Test",
            clerk_org_id="org_test",
            workos_organization_id="org_01workos",
        )
        org.workos_organization_id = None
        assert org.workos_organization_id is None
