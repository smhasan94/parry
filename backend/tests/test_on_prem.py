"""Unit tests for the on_prem module.

Exercises the settings-driven startup loader without touching the
real license file or public key.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import on_prem
from app.core.config import settings
from app.services.license_service import LicenseError, _canonical_payload


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pub


def _write_license(path: Path, priv: Ed25519PrivateKey, **overrides) -> None:
    payload = {
        "schema_version": "1.0",
        "license_id": "lic_test",
        "customer_name": "Acme",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "max_agents": 10,
        "max_events_per_month": 50_000,
        "features": ["custom_rules"],
    }
    payload.update(overrides)
    sig = base64.b64encode(priv.sign(_canonical_payload(payload))).decode("ascii")
    path.write_text(json.dumps({"payload": payload, "signature": sig}))


@pytest.fixture(autouse=True)
def _reset() -> None:
    on_prem.reset_for_tests()
    yield
    on_prem.reset_for_tests()


def test_non_on_prem_startup_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "on_prem_mode", False)
    on_prem.load_on_startup()
    assert on_prem.is_on_prem() is False
    assert on_prem.get_license() is None


def test_on_prem_without_public_key_hard_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "on_prem_mode", True)
    monkeypatch.setattr(settings, "license_public_key_pem", "")
    with pytest.raises(LicenseError, match="license_public_key_pem"):
        on_prem.load_on_startup()


def test_on_prem_loads_valid_license(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    priv, pub = _keypair()
    license_path = tmp_path / "parry.license"
    _write_license(license_path, priv)

    monkeypatch.setattr(settings, "on_prem_mode", True)
    monkeypatch.setattr(settings, "license_public_key_pem", pub)
    monkeypatch.setattr(settings, "license_path", str(license_path))

    on_prem.load_on_startup()
    lic = on_prem.get_license()
    assert lic is not None
    assert lic.customer_name == "Acme"
    assert lic.max_agents == 10


def test_on_prem_missing_file_hard_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, pub = _keypair()
    monkeypatch.setattr(settings, "on_prem_mode", True)
    monkeypatch.setattr(settings, "license_public_key_pem", pub)
    monkeypatch.setattr(settings, "license_path", str(tmp_path / "does-not-exist"))
    with pytest.raises(LicenseError, match="not found"):
        on_prem.load_on_startup()


def test_on_prem_wrong_key_hard_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    priv, _ = _keypair()
    _, other_pub = _keypair()  # different keypair
    license_path = tmp_path / "parry.license"
    _write_license(license_path, priv)

    monkeypatch.setattr(settings, "on_prem_mode", True)
    monkeypatch.setattr(settings, "license_public_key_pem", other_pub)
    monkeypatch.setattr(settings, "license_path", str(license_path))

    with pytest.raises(LicenseError, match="signature is invalid"):
        on_prem.load_on_startup()
