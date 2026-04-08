"""Unit tests for sso_service.

No WorkOS SDK required — we feed a hand-rolled mock client through
the service functions and assert the adapter translates cleanly.
This keeps the backend build + test suite working on machines that
never install ``workos``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.services import sso_service
from app.services.sso_service import (
    SSOError,
    SSOProfile,
    _profile_from_workos,
    exchange_code,
    get_authorization_url,
    get_client,
)


class _MockSSO:
    def __init__(self, url: str = "https://workos.example/auth/abc", profile: Any = None):
        self._url = url
        self._profile = profile
        self.last_args: dict = {}

    def get_authorization_url(self, **kwargs: Any) -> str:
        self.last_args = kwargs
        return self._url

    def get_profile_and_token(self, **kwargs: Any) -> Any:
        self.last_args = kwargs
        if self._profile is None:
            raise RuntimeError("exchange not configured")
        return self._profile


class _MockPortal:
    def __init__(self, url: str = "https://setup.workos.com/portal/abc"):
        self._url = url
        self.last_args: dict = {}

    def generate_link(self, **kwargs: Any) -> str:
        self.last_args = kwargs
        return self._url


class _MockClient:
    def __init__(self, sso: _MockSSO | None = None, portal: _MockPortal | None = None):
        self.sso = sso or _MockSSO()
        self.portal = portal or _MockPortal()


# ── get_client ───────────────────────────────────────────────────────


def test_get_client_returns_none_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_api_key", "")
    monkeypatch.setattr(settings, "workos_client_id", "")
    assert get_client() is None


def test_get_client_returns_none_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the workos SDK not being installed — patch sys.modules
    # so the import inside get_client raises.
    import builtins

    monkeypatch.setattr(settings, "workos_api_key", "sk_test")
    monkeypatch.setattr(settings, "workos_client_id", "client_test")

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name == "workos":
            raise ImportError("no workos for you")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert get_client() is None


# ── get_authorization_url ───────────────────────────────────────────


def test_get_authorization_url_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_redirect_uri", "https://app/cb")
    client = _MockClient()
    url = get_authorization_url(
        client, organization_id="org_123", state="tab-1"
    )
    assert url == "https://workos.example/auth/abc"
    assert client.sso.last_args["organization_id"] == "org_123"
    assert client.sso.last_args["redirect_uri"] == "https://app/cb"
    assert client.sso.last_args["state"] == "tab-1"


def test_get_authorization_url_overrides_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_redirect_uri", "https://app/cb")
    client = _MockClient()
    get_authorization_url(
        client,
        organization_id="org_123",
        redirect_uri="https://other/cb",
    )
    assert client.sso.last_args["redirect_uri"] == "https://other/cb"


def test_get_authorization_url_requires_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_redirect_uri", "")
    client = _MockClient()
    with pytest.raises(SSOError, match="workos_redirect_uri"):
        get_authorization_url(client, organization_id="org_1")


def test_get_authorization_url_requires_org_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_redirect_uri", "https://app/cb")
    client = _MockClient()
    with pytest.raises(SSOError, match="organization_id"):
        get_authorization_url(client, organization_id="")


def test_get_authorization_url_wraps_sdk_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "workos_redirect_uri", "https://app/cb")

    class Boom:
        sso = SimpleNamespace(
            get_authorization_url=lambda **_: (_ for _ in ()).throw(
                RuntimeError("down")
            )
        )
        portal = _MockPortal()

    with pytest.raises(SSOError, match="Failed to build"):
        get_authorization_url(Boom(), organization_id="org_1")


# ── _profile_from_workos ────────────────────────────────────────────


def test_profile_from_workos_dict_shape() -> None:
    raw = {
        "profile": {
            "id": "user_01",
            "email": "alice@example.com",
            "organization_id": "org_123",
            "first_name": "Alice",
            "last_name": "Anderson",
        }
    }
    profile = _profile_from_workos(raw)
    assert profile.workos_user_id == "user_01"
    assert profile.workos_organization_id == "org_123"
    assert profile.email == "alice@example.com"
    assert profile.display_name == "Alice Anderson"


def test_profile_from_workos_attribute_shape() -> None:
    raw = SimpleNamespace(
        profile=SimpleNamespace(
            id="user_02",
            email="bob@example.com",
            organization_id="org_456",
            first_name=None,
            last_name=None,
        )
    )
    profile = _profile_from_workos(raw)
    assert profile.workos_user_id == "user_02"
    assert profile.display_name == "bob@example.com"  # falls back to email


def test_profile_from_workos_missing_email_raises() -> None:
    raw = {"profile": {"id": "user_03"}}
    with pytest.raises(SSOError, match="missing id or email"):
        _profile_from_workos(raw)


def test_profile_from_workos_bare_profile_supported() -> None:
    # Some SDK versions return the profile directly, not wrapped.
    raw = {"id": "user_04", "email": "carol@example.com"}
    profile = _profile_from_workos(raw)
    assert profile.workos_user_id == "user_04"


# ── exchange_code ────────────────────────────────────────────────────


def test_exchange_code_happy_path() -> None:
    client = _MockClient(
        sso=_MockSSO(
            profile={
                "profile": {
                    "id": "user_99",
                    "email": "dave@example.com",
                    "organization_id": "org_789",
                    "first_name": "Dave",
                    "last_name": None,
                }
            }
        )
    )
    profile = exchange_code(client, code="abc")
    assert isinstance(profile, SSOProfile)
    assert profile.workos_user_id == "user_99"
    assert profile.workos_organization_id == "org_789"
    assert client.sso.last_args == {"code": "abc"}


def test_exchange_code_requires_code() -> None:
    with pytest.raises(SSOError, match="Missing authorization code"):
        exchange_code(_MockClient(), code="")


def test_exchange_code_wraps_sdk_failure() -> None:
    client = _MockClient()  # profile=None → raises in _MockSSO
    with pytest.raises(SSOError, match="exchange failed"):
        exchange_code(client, code="abc")


# ── admin_portal_url ─────────────────────────────────────────────────


def test_admin_portal_url_happy_path() -> None:
    client = _MockClient()
    url = sso_service.admin_portal_url(
        client,
        organization_id="org_123",
        return_url="https://app/settings",
    )
    assert url.startswith("https://setup.workos.com")
    assert client.portal.last_args == {
        "organization": "org_123",
        "intent": "sso",
        "return_url": "https://app/settings",
    }


def test_admin_portal_url_requires_org_id() -> None:
    with pytest.raises(SSOError, match="organization_id is required"):
        sso_service.admin_portal_url(_MockClient(), organization_id="")
