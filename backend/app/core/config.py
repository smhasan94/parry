import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://parry:parry@localhost:5432/parry"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Anthropic
    anthropic_api_key: str = ""

    # Clerk
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    clerk_webhook_secret: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_growth: str = ""
    stripe_price_id_pro: str = ""

    # Internal auth
    parry_internal_secret: str = "change-me"

    # CORS
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # Dashboard URL (used in alert links)
    dashboard_url: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_production(self) -> None:
        """Fail fast if critical env vars are missing in production."""
        if not self.is_production:
            return

        missing = []
        if self.app_secret_key == "change-me-in-production":
            missing.append("APP_SECRET_KEY")
        if not self.clerk_secret_key:
            missing.append("CLERK_SECRET_KEY")
        if not self.clerk_webhook_secret:
            missing.append("CLERK_WEBHOOK_SECRET")
        if self.parry_internal_secret == "change-me":
            missing.append("PARRY_INTERNAL_SECRET")

        if missing:
            raise ValueError(
                f"Production requires these env vars: {', '.join(missing)}. "
                "Set APP_ENV=development to skip this check."
            )

    def log_startup_warnings(self) -> None:
        """Log warnings for missing optional config that limits functionality."""
        if not self.anthropic_api_key:
            log.warning(
                "config.missing",
                var="ANTHROPIC_API_KEY",
                impact="LLM fallback detector disabled",
            )
        if not self.clerk_secret_key:
            log.warning(
                "config.missing",
                var="CLERK_SECRET_KEY",
                impact="Auth disabled, using demo org",
            )
        if not self.stripe_secret_key:
            log.warning(
                "config.missing",
                var="STRIPE_SECRET_KEY",
                impact="Billing endpoints will return 503",
            )


settings = Settings()
