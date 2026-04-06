"""Sentry error tracking initialization (no-op when SENTRY_DSN unset)."""
import structlog

from app.core.config import settings

log = structlog.get_logger()


def init_sentry() -> bool:
    """Initialize Sentry SDK if SENTRY_DSN is configured.

    Returns True if Sentry was initialized, False if skipped.
    Safe to call when sentry-sdk is missing — will log and return False.
    """
    if not settings.sentry_dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        log.warning("sentry.import_failed", msg="sentry-sdk not installed")
        return False

    environment = settings.sentry_environment or settings.app_env

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Strip PII — Parry processes prompts and responses that may contain user data.
        send_default_pii=False,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            AsyncioIntegration(),
        ],
        before_send=_strip_sensitive_fields,
    )
    log.info("sentry.initialized", environment=environment)
    return True


def _strip_sensitive_fields(event: dict, _hint: dict) -> dict | None:
    """Remove fields that may contain user prompts or API keys before sending."""
    # Strip request body — may contain prompts/responses
    if "request" in event and isinstance(event["request"], dict):
        event["request"].pop("data", None)
        # Strip auth headers
        headers = event["request"].get("headers") or {}
        for k in list(headers.keys()):
            if k.lower() in ("authorization", "x-parry-secret", "cookie"):
                headers[k] = "[Filtered]"
    return event
