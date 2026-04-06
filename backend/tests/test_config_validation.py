"""Tests for Settings.validate_for_production() and log_startup_warnings()."""
import pytest

from app.core.config import Settings


def _settings(**overrides) -> Settings:
    """Build a Settings object that ignores .env files (avoids leakage)."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestValidateForProduction:
    def test_dev_env_skips_validation(self) -> None:
        """Development should never raise even with all secrets missing."""
        s = _settings(app_env="development")
        s.validate_for_production()  # should not raise

    def test_production_with_all_secrets_passes(self) -> None:
        s = _settings(
            app_env="production",
            app_secret_key="real-secret",
            clerk_secret_key="sk_live_xxx",
            clerk_webhook_secret="whsec_xxx",
            parry_internal_secret="real-internal",
        )
        s.validate_for_production()  # should not raise

    def test_production_with_default_app_secret_fails(self) -> None:
        s = _settings(
            app_env="production",
            clerk_secret_key="sk_live_xxx",
            clerk_webhook_secret="whsec_xxx",
            parry_internal_secret="real-internal",
        )
        with pytest.raises(ValueError, match="APP_SECRET_KEY"):
            s.validate_for_production()

    def test_production_with_default_internal_secret_fails(self) -> None:
        s = _settings(
            app_env="production",
            app_secret_key="real-secret",
            clerk_secret_key="sk_live_xxx",
            clerk_webhook_secret="whsec_xxx",
        )
        with pytest.raises(ValueError, match="PARRY_INTERNAL_SECRET"):
            s.validate_for_production()

    def test_production_missing_clerk_fails(self) -> None:
        s = _settings(
            app_env="production",
            app_secret_key="real-secret",
            parry_internal_secret="real-internal",
        )
        with pytest.raises(ValueError) as exc:
            s.validate_for_production()
        assert "CLERK_SECRET_KEY" in str(exc.value)
        assert "CLERK_WEBHOOK_SECRET" in str(exc.value)

    def test_error_lists_all_missing_at_once(self) -> None:
        s = _settings(app_env="production")
        with pytest.raises(ValueError) as exc:
            s.validate_for_production()
        msg = str(exc.value)
        # Should report all four missing in a single error, not raise on the first
        assert "APP_SECRET_KEY" in msg
        assert "CLERK_SECRET_KEY" in msg
        assert "CLERK_WEBHOOK_SECRET" in msg
        assert "PARRY_INTERNAL_SECRET" in msg


class TestLogStartupWarnings:
    def test_does_not_raise_when_optional_missing(self) -> None:
        """Warnings should never raise — they just log."""
        s = _settings()
        s.log_startup_warnings()

    def test_does_not_raise_when_all_set(self) -> None:
        s = _settings(
            anthropic_api_key="sk-ant-xxx",
            clerk_secret_key="sk_live_xxx",
            stripe_secret_key="sk_live_xxx",
        )
        s.log_startup_warnings()


class TestIsProduction:
    def test_dev(self) -> None:
        assert _settings(app_env="development").is_production is False

    def test_production(self) -> None:
        assert _settings(app_env="production").is_production is True

    def test_other_envs_are_not_production(self) -> None:
        assert _settings(app_env="staging").is_production is False
        assert _settings(app_env="test").is_production is False


class TestCorsOrigins:
    def test_single_origin(self) -> None:
        s = _settings(allowed_origins="http://localhost:5173")
        assert s.cors_origins == ["http://localhost:5173"]

    def test_multiple_origins(self) -> None:
        s = _settings(allowed_origins="http://a.com,http://b.com,http://c.com")
        assert s.cors_origins == ["http://a.com", "http://b.com", "http://c.com"]

    def test_strips_whitespace(self) -> None:
        s = _settings(allowed_origins="http://a.com , http://b.com")
        assert s.cors_origins == ["http://a.com", "http://b.com"]
