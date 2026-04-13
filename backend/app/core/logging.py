import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import settings

# Patterns that indicate sensitive values in log event dicts.
# Matches common key names; values are replaced with a redaction marker.
_SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|authorization|credential|ssn|"
    r"credit[_-]?card|private[_-]?key)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"

# Inline patterns for values that look like secrets even when the key
# name doesn't hint at it (e.g. sk-parry-... or Bearer tokens).
_SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-parry-[A-Za-z0-9]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def _redact_value(value: Any) -> Any:
    """Redact a value if it looks like a secret."""
    if not isinstance(value, str):
        return value
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            return _REDACTED
    return value


def _redact_event_dict(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that scrubs sensitive keys and values."""
    for key in list(event_dict.keys()):
        if _SENSITIVE_KEYS.search(key):
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def setup_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_event_dict,
            (
                structlog.dev.ConsoleRenderer()
                if not settings.is_production
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy third-party loggers
    for name in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)
