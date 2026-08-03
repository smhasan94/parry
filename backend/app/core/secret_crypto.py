"""Symmetric encryption for third-party credentials stored at rest.

Probe credentials are live tokens against a customer's identity provider
— an Okta token here can read every app assignment in their directory.
A database dump must not be enough to use one.

Fernet (AES-128-CBC + HMAC-SHA256) is used rather than raw AES: it is
authenticated, so a tampered ciphertext fails loudly instead of
decrypting to attacker-chosen bytes, and it carries a random IV, so the
same token does not produce the same ciphertext twice.

Every path here fails closed. If no key is configured we refuse to
encrypt rather than fall back to storing plaintext, because the failure
mode of the alternative is silent and permanent.
"""

from __future__ import annotations

import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import ConfigurationError

log = structlog.get_logger()


class DecryptionError(Exception):
    """Ciphertext could not be decrypted with the configured key.

    Deliberately not a ParryError: this should never reach an HTTP
    response as a domain error. It means the key rotated without
    re-encryption, the row was tampered with, or the wrong environment's
    key is loaded — all of which want a 500 and an alert, not a
    user-facing message.
    """


def generate_key() -> str:
    """Mint a key for `PROBE_ENCRYPTION_KEY`.

    uv run python -c "from app.core.secret_crypto import generate_key; print(generate_key())"
    """
    return Fernet.generate_key().decode()


def is_configured() -> bool:
    """Whether credential storage is available at all.

    Callers use this to disable the feature cleanly rather than let a
    write fail halfway through a request.
    """
    return bool(settings.probe_encryption_key)


def _cipher() -> Fernet:
    key = settings.probe_encryption_key
    if not key:
        raise ConfigurationError(
            "PROBE_ENCRYPTION_KEY is not set — refusing to handle credentials. "
            "Generate one with: python -c "
            "'from app.core.secret_crypto import generate_key; print(generate_key())'"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(
            "PROBE_ENCRYPTION_KEY is not a valid Fernet key (expected 32 "
            "url-safe base64-encoded bytes)"
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a credential for storage. Never log the return value's input."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Recover a credential for immediate use. Do not persist the result."""
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        # No detail in the message — which key failed and on what row is
        # exactly what an attacker probing this would want.
        log.error("secret_decrypt_failed")
        raise DecryptionError("stored credential could not be decrypted") from exc
