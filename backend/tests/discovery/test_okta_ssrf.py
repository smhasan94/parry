"""SSRF guards on the Okta client.

``okta_domain`` arrives in a request body and is fetched server-side with
an Authorization header attached. In multi-tenant SaaS the caller is a
customer admin — authenticated, but not trusted to steer Parry's own
outbound requests at Parry's internal network.
"""

from __future__ import annotations

import pytest

from app.discovery.okta import OktaDomainError, resolve_base_url, validate_next_url


class TestDomainValidation:
    @pytest.mark.parametrize(
        "domain",
        [
            "acme.okta.com",
            "acme-corp.okta.com",
            "acme.oktapreview.com",
            "acme.okta-emea.com",
            "a1.okta.com",
        ],
    )
    def test_accepts_real_okta_tenants(self, domain: str) -> None:
        assert resolve_base_url(domain) == f"https://{domain}"

    def test_rejects_the_cloud_metadata_endpoint(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("169.254.169.254")

    def test_rejects_a_path_smuggled_into_the_domain(self) -> None:
        # https://169.254.169.254/latest/meta-data#/api/v1/apps — the
        # fragment swallows the path the client meant to append.
        with pytest.raises(OktaDomainError):
            resolve_base_url("169.254.169.254/latest/meta-data#")

    def test_rejects_userinfo_pointing_at_another_host(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("acme.okta.com@evil.test")

    def test_rejects_a_suffix_lookalike_domain(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("acme.okta.com.evil.test")

    def test_rejects_an_explicit_port(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("acme.okta.com:8080")

    def test_rejects_a_query_string(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("acme.okta.com/?x=1")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("localhost")

    def test_rejects_an_internal_hostname(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("postgres.internal")

    def test_rejects_a_scheme_prefix(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("http://acme.okta.com")

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(OktaDomainError):
            resolve_base_url("")

    def test_normalizes_case_and_surrounding_whitespace(self) -> None:
        assert resolve_base_url("  ACME.Okta.com  ") == "https://acme.okta.com"


class TestPaginationGuard:
    def test_accepts_a_next_link_on_the_validated_host(self) -> None:
        url = "https://acme.okta.com/api/v1/apps?after=xyz"

        assert validate_next_url(url, "acme.okta.com") == url

    def test_rejects_a_next_link_that_pivots_to_another_host(self) -> None:
        # A malicious or compromised upstream returning
        # Link: <http://169.254.169.254/>; rel="next" must not be followed
        # with the Authorization header still attached.
        with pytest.raises(OktaDomainError):
            validate_next_url("http://169.254.169.254/", "acme.okta.com")

    def test_rejects_a_next_link_that_downgrades_to_http(self) -> None:
        with pytest.raises(OktaDomainError):
            validate_next_url("http://acme.okta.com/api/v1/apps", "acme.okta.com")

    def test_rejects_a_next_link_to_a_different_okta_tenant(self) -> None:
        with pytest.raises(OktaDomainError):
            validate_next_url("https://other.okta.com/api/v1/apps", "acme.okta.com")

    def test_returns_none_when_there_is_no_next_link(self) -> None:
        assert validate_next_url(None, "acme.okta.com") is None
