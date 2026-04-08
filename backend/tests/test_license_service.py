"""Unit tests for license_service.

Generates an ephemeral Ed25519 keypair per test so we don't need
fixture files on disk and so test state can't leak into production
code paths.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.license_service import (
    License,
    LicenseError,
    _canonical_payload,
    load_license,
    verify_license,
)


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pub_pem


def _sign(priv: Ed25519PrivateKey, payload: dict[str, Any]) -> dict[str, Any]:
    sig = priv.sign(_canonical_payload(payload))
    return {"payload": payload, "signature": base64.b64encode(sig).decode("ascii")}


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "license_id": "lic_test_1",
        "customer_name": "Acme Corp",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "max_agents": 100,
        "max_events_per_month": 5_000_000,
        "features": ["custom_rules", "compliance_export"],
    }
    base.update(overrides)
    return base


# ── Happy path ───────────────────────────────────────────────────────


def test_verify_valid_license_returns_typed_license() -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload())
    lic = verify_license(raw, pub)
    assert isinstance(lic, License)
    assert lic.license_id == "lic_test_1"
    assert lic.customer_name == "Acme Corp"
    assert lic.max_agents == 100
    assert lic.max_events_per_month == 5_000_000
    assert lic.has_feature("custom_rules")
    assert not lic.has_feature("sso")


def test_verify_supports_unlimited_fields() -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload(max_agents=None, max_events_per_month=None))
    lic = verify_license(raw, pub)
    assert lic.max_agents is None
    assert lic.max_events_per_month is None


def test_is_expired() -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload(expires_at="2020-01-01T00:00:00+00:00"))
    lic = verify_license(raw, pub)
    assert lic.is_expired() is True

    raw = _sign(priv, _payload(expires_at="2099-01-01T00:00:00+00:00"))
    lic = verify_license(raw, pub)
    assert lic.is_expired() is False


# ── Signature validation ────────────────────────────────────────────


def test_verify_rejects_tampered_payload() -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload())
    raw["payload"]["max_agents"] = 999_999  # tamper after signing
    with pytest.raises(LicenseError, match="signature is invalid"):
        verify_license(raw, pub)


def test_verify_rejects_swapped_signature() -> None:
    priv, pub = _keypair()
    good = _sign(priv, _payload())
    different = _sign(priv, _payload(license_id="lic_other"))
    # Swap the signature onto a different payload — should fail.
    good["signature"] = different["signature"]
    with pytest.raises(LicenseError):
        verify_license(good, pub)


def test_verify_rejects_wrong_public_key() -> None:
    priv, _ = _keypair()
    _, other_pub = _keypair()
    raw = _sign(priv, _payload())
    with pytest.raises(LicenseError, match="signature is invalid"):
        verify_license(raw, other_pub)


# ── Input validation ────────────────────────────────────────────────


def test_verify_rejects_non_dict_root() -> None:
    _, pub = _keypair()
    with pytest.raises(LicenseError, match="must be a JSON object"):
        verify_license([], pub)  # type: ignore[arg-type]


def test_verify_rejects_missing_signature() -> None:
    _, pub = _keypair()
    with pytest.raises(LicenseError, match="missing payload or signature"):
        verify_license({"payload": _payload()}, pub)


def test_verify_rejects_non_base64_signature() -> None:
    _, pub = _keypair()
    with pytest.raises(LicenseError, match="not valid base64"):
        verify_license({"payload": _payload(), "signature": "!!!"}, pub)


def test_verify_rejects_invalid_public_key_pem() -> None:
    priv, _ = _keypair()
    raw = _sign(priv, _payload())
    with pytest.raises(LicenseError, match="Invalid license public key PEM"):
        verify_license(raw, "not a pem")


def test_verify_rejects_non_ed25519_public_key() -> None:
    priv, _ = _keypair()
    raw = _sign(priv, _payload())
    # RSA key in PEM form — valid PEM but wrong algorithm.
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pub_pem = rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    with pytest.raises(LicenseError, match="must be Ed25519"):
        verify_license(raw, rsa_pub_pem)


def test_verify_rejects_missing_required_field() -> None:
    priv, pub = _keypair()
    payload = _payload()
    del payload["customer_name"]
    raw = _sign(priv, payload)
    with pytest.raises(LicenseError, match="missing required fields"):
        verify_license(raw, pub)


def test_verify_rejects_negative_max_agents() -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload(max_agents=-5))
    with pytest.raises(LicenseError):
        verify_license(raw, pub)


def test_verify_rejects_bool_for_int_fields() -> None:
    # bool is a subclass of int in Python; reject explicitly.
    priv, pub = _keypair()
    raw = _sign(priv, _payload(max_agents=True))
    with pytest.raises(LicenseError):
        verify_license(raw, pub)


# ── load_license from disk ──────────────────────────────────────────


def test_load_license_from_file(tmp_path: Path) -> None:
    priv, pub = _keypair()
    raw = _sign(priv, _payload())
    license_path = tmp_path / "parry.license"
    license_path.write_text(json.dumps(raw))
    lic = load_license(str(license_path), pub)
    assert lic.license_id == "lic_test_1"


def test_load_license_missing_file_raises() -> None:
    _, pub = _keypair()
    with pytest.raises(LicenseError, match="not found"):
        load_license("/nonexistent/path/parry.license", pub)


def test_load_license_malformed_json_raises(tmp_path: Path) -> None:
    _, pub = _keypair()
    path = tmp_path / "parry.license"
    path.write_text("{not json")
    with pytest.raises(LicenseError, match="not valid JSON"):
        load_license(str(path), pub)


# ── _canonical_payload determinism ──────────────────────────────────


def test_canonical_payload_is_key_order_independent() -> None:
    a = {"z": 1, "a": 2, "m": 3}
    b = {"a": 2, "m": 3, "z": 1}
    assert _canonical_payload(a) == _canonical_payload(b)


def test_canonical_payload_is_stable_across_calls() -> None:
    payload = _payload()
    assert _canonical_payload(payload) == _canonical_payload(payload)
