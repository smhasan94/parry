"""Tests for app.core.sentry.init_sentry and _strip_sensitive_fields."""
from app.core.config import settings
from app.core.sentry import _strip_sensitive_fields, init_sentry


class TestInitSentry:
    def test_no_op_when_dsn_unset(self, monkeypatch) -> None:
        """init_sentry returns False when SENTRY_DSN is empty (no-op)."""
        monkeypatch.setattr(settings, "sentry_dsn", "")
        assert init_sentry() is False

    def test_init_attempted_when_dsn_set(self, monkeypatch) -> None:
        """When DSN is set, init_sentry should call sentry_sdk.init and return True."""
        monkeypatch.setattr(settings, "sentry_dsn", "https://fake@sentry.io/0")
        # Sentry's init is idempotent and accepts a fake DSN format without
        # validating the host until an actual event is sent.
        result = init_sentry()
        assert result is True


class TestStripSensitiveFields:
    def test_strips_request_data(self) -> None:
        event = {"request": {"data": {"prompt": "secret data"}}}
        result = _strip_sensitive_fields(event, {})
        assert result is not None
        assert "data" not in result["request"]

    def test_filters_authorization_header(self) -> None:
        event = {
            "request": {
                "headers": {
                    "Authorization": "Bearer sk-real-token",
                    "Content-Type": "application/json",
                }
            }
        }
        result = _strip_sensitive_fields(event, {})
        assert result is not None
        assert result["request"]["headers"]["Authorization"] == "[Filtered]"
        # Non-sensitive headers preserved
        assert result["request"]["headers"]["Content-Type"] == "application/json"

    def test_filters_x_parry_secret(self) -> None:
        event = {
            "request": {
                "headers": {"X-Parry-Secret": "sk-parry-real-key"},
            }
        }
        result = _strip_sensitive_fields(event, {})
        assert result["request"]["headers"]["X-Parry-Secret"] == "[Filtered]"

    def test_filters_cookie_header(self) -> None:
        event = {"request": {"headers": {"Cookie": "session=abc123"}}}
        result = _strip_sensitive_fields(event, {})
        assert result["request"]["headers"]["Cookie"] == "[Filtered]"

    def test_filtering_is_case_insensitive(self) -> None:
        event = {
            "request": {
                "headers": {"authorization": "Bearer xxx", "x-parry-secret": "sk-yyy"}
            }
        }
        result = _strip_sensitive_fields(event, {})
        assert result["request"]["headers"]["authorization"] == "[Filtered]"
        assert result["request"]["headers"]["x-parry-secret"] == "[Filtered]"

    def test_no_request_section(self) -> None:
        """Events without a request section should pass through unchanged."""
        event = {"exception": {"values": []}}
        result = _strip_sensitive_fields(event, {})
        assert result == event

    def test_request_without_headers(self) -> None:
        event = {"request": {}}
        result = _strip_sensitive_fields(event, {})
        assert result is not None
