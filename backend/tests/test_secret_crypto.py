"""Encryption for probe credentials at rest.

These secrets are live third-party API tokens — an Okta token that can
read every app assignment in a customer's directory. A database dump
must not be enough to use them.
"""

from __future__ import annotations

import pytest

from app.core import secret_crypto
from app.core.exceptions import ConfigurationError


def _key() -> str:
    return secret_crypto.generate_key()


def test_round_trips_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())

    ciphertext = secret_crypto.encrypt_secret("00Ab-okta-token")

    assert secret_crypto.decrypt_secret(ciphertext) == "00Ab-okta-token"


def test_ciphertext_does_not_contain_the_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())

    ciphertext = secret_crypto.encrypt_secret("00Ab-okta-token")

    assert "okta-token" not in ciphertext


def test_the_same_secret_encrypts_differently_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())

    first = secret_crypto.encrypt_secret("same-token")
    second = secret_crypto.encrypt_secret("same-token")

    # Deterministic ciphertext would let anyone with read access tell
    # which orgs share a token without decrypting anything.
    assert first != second
    assert secret_crypto.decrypt_secret(first) == secret_crypto.decrypt_secret(second)


def test_a_different_key_cannot_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())
    ciphertext = secret_crypto.encrypt_secret("00Ab-okta-token")

    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())

    with pytest.raises(secret_crypto.DecryptionError):
        secret_crypto.decrypt_secret(ciphertext)


def test_tampered_ciphertext_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())
    ciphertext = secret_crypto.encrypt_secret("00Ab-okta-token")

    tampered = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")

    # Fernet is authenticated; a modified token must fail rather than
    # decrypt to something attacker-chosen.
    with pytest.raises(secret_crypto.DecryptionError):
        secret_crypto.decrypt_secret(tampered)


def test_encrypting_without_a_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "")

    # The dangerous failure mode is storing the token in plaintext
    # because nobody configured a key. Refuse instead.
    with pytest.raises(ConfigurationError):
        secret_crypto.encrypt_secret("00Ab-okta-token")


def test_decrypting_without_a_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "")

    with pytest.raises(ConfigurationError):
        secret_crypto.decrypt_secret("gAAAAA-whatever")


def test_a_malformed_key_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "not-a-fernet-key")

    with pytest.raises(ConfigurationError):
        secret_crypto.encrypt_secret("00Ab-okta-token")


def test_generated_keys_are_usable_and_distinct() -> None:
    first, second = secret_crypto.generate_key(), secret_crypto.generate_key()

    assert first != second
    assert len(first) > 30


def test_is_configured_reports_key_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", "")
    assert secret_crypto.is_configured() is False

    monkeypatch.setattr(secret_crypto.settings, "probe_encryption_key", _key())
    assert secret_crypto.is_configured() is True
