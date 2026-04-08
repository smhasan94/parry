"""On-prem mode global state.

Tiny module so the rest of the codebase can answer three questions
without each call site having to know about license file paths,
PEM keys, or Settings:

- ``is_on_prem()`` — is the process running in air-gapped mode?
- ``get_license()`` — return the verified License (or None)
- ``require_feature(name)`` — raise if a feature isn't in the license

The license is loaded once at application startup (see main.lifespan)
and cached in module-level state. A failed verification in on-prem
mode is fatal — we never silently fall back to SaaS behaviour.
"""
from __future__ import annotations

import structlog

from app.core.config import settings
from app.services.license_service import License, LicenseError, load_license

log = structlog.get_logger()

_license: License | None = None
_loaded: bool = False


def is_on_prem() -> bool:
    """Return True if the backend is running in air-gapped on-prem mode."""
    return settings.on_prem_mode


def get_license() -> License | None:
    """Return the currently-loaded license, or None when not on-prem."""
    return _license


def load_on_startup() -> None:
    """Verify the license file at startup. Called from the lifespan hook.

    Raises ``LicenseError`` in on-prem mode if the file is missing,
    tampered, or signed with the wrong key — startup should hard-fail
    rather than come up in a degraded state.
    """
    global _license, _loaded
    _loaded = True
    if not settings.on_prem_mode:
        return

    if not settings.license_public_key_pem:
        raise LicenseError(
            "on_prem_mode is enabled but license_public_key_pem is empty"
        )

    _license = load_license(settings.license_path, settings.license_public_key_pem)
    log.info(
        "license.loaded",
        license_id=_license.license_id,
        customer=_license.customer_name,
        expires_at=_license.expires_at.isoformat(),
        max_agents=_license.max_agents,
        max_events_per_month=_license.max_events_per_month,
        features=list(_license.features),
        expired=_license.is_expired(),
    )


def reset_for_tests() -> None:
    """Clear cached state. Tests only — never call from production code."""
    global _license, _loaded
    _license = None
    _loaded = False
