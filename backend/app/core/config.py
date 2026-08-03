from pathlib import Path

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger()

# Anchored to the repo, not the process cwd. Commands run from backend/
# (alembic, uvicorn, scripts) would otherwise miss the root .env and fall
# back to these defaults — which fails confusingly against whatever else
# happens to be listening on the default port.
_REPO_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # Later entries win, so a backend/.env still overrides the repo root.
    # extra="ignore" because the root .env is shared with the dashboard and
    # carries VITE_* keys that are none of the backend's business. Tradeoff:
    # a misspelled backend var is now silently ignored rather than fatal.
    model_config = SettingsConfigDict(
        env_file=(_REPO_ENV, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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

    # SMTP (email alerts)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "alerts@parry.dev"
    smtp_use_tls: bool = True

    # Sentry (error tracking — optional)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_environment: str = ""

    # SOC 2 audit log export to S3 (optional — missing bucket = disabled).
    # Scheduled monthly task writes one JSON artefact per org per month.
    audit_export_s3_bucket: str = ""
    audit_export_s3_prefix: str = "audit-log"
    audit_export_s3_region: str = "us-east-1"
    audit_export_aws_access_key_id: str = ""
    audit_export_aws_secret_access_key: str = ""

    # On-prem mode — air-gapped deployment, enforced by a signed
    # license file. When enabled:
    #   * Stripe metered usage reporting is a no-op
    #   * Monthly S3 audit export is a no-op
    #   * LLM fallback is disabled (no outbound Anthropic calls)
    #   * plan_service reads limits from the license, not the org row
    #   * Startup is a hard-fail if the license can't be verified
    on_prem_mode: bool = False
    license_path: str = "/etc/parry/parry.license"
    # Baked-in Ed25519 public key for license verification. Override
    # via env var in dev; production builds ship with this populated.
    license_public_key_pem: str = ""

    # WorkOS SSO (enterprise SAML). Optional — only orgs that flip on
    # SAML in their settings need these. Missing values mean
    # sso_service.get_client() returns None and the /sso routes 503.
    workos_api_key: str = ""
    workos_client_id: str = ""
    # Where WorkOS should redirect after a successful SAML flow. The
    # dashboard handles this path and swaps the code for a session.
    workos_redirect_uri: str = ""

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
