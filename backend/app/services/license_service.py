"""Offline license files for on-prem deployments.

A Parry on-prem install runs air-gapped — no phone-home, no Stripe,
no metered usage. Licensing is enforced by a signed JSON file the
customer drops on disk at startup. The backend verifies the signature
with a baked-in Ed25519 public key and exposes the decoded payload
through ``load_license``.

File format (wire):

```json
{
  "payload": {
    "schema_version": "1.0",
    "license_id": "lic_abc123",
    "customer_name": "Acme Corp",
    "issued_at": "2026-01-01T00:00:00+00:00",
    "expires_at": "2027-01-01T00:00:00+00:00",
    "max_agents": 100,
    "max_events_per_month": 5000000,
    "features": ["custom_rules", "compliance_export"]
  },
  "signature": "base64-ed25519-signature-over-canonical-payload"
}
```

The signature covers the canonical JSON form of ``payload`` (sorted
keys, no whitespace) — identical to the scheme used by
``audit_export_service`` so customers only have to learn one
verification recipe. Any field tampering or a forged signature is
detected by ``verify_license`` and ``load_license`` raises.

Key management: Parry ships a **single** hard-coded public key in
``settings.license_public_key_pem`` (env-injectable for dev). The
corresponding private key lives in Parry's internal vault and is
used by the ``scripts/generate_license.py`` CLI when issuing a
license to a new customer.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

log = structlog.get_logger()


class LicenseError(Exception):
    """Raised for any unrecoverable license error — missing, malformed,
    unsigned, expired, or wrong public key. The startup path treats this
    as fatal in on-prem mode."""


@dataclass(frozen=True)
class License:
    license_id: str
    customer_name: str
    issued_at: datetime
    expires_at: datetime
    max_agents: int | None
    max_events_per_month: int | None
    features: tuple[str, ...]
    schema_version: str

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at

    def has_feature(self, feature: str) -> bool:
        return feature in self.features


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding matching the signing tool."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _load_public_key(pem: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise LicenseError(f"Invalid license public key PEM: {e}") from e
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseError("License public key must be Ed25519")
    return key


def verify_license(raw: dict[str, Any], public_key_pem: str) -> License:
    """Verify the envelope's signature and return a typed License.

    Raises ``LicenseError`` for any problem — we never silently
    downgrade a bad license to partial enforcement.
    """
    if not isinstance(raw, dict):
        raise LicenseError("License file must be a JSON object")

    payload = raw.get("payload")
    sig_b64 = raw.get("signature")
    if not isinstance(payload, dict) or not isinstance(sig_b64, str):
        raise LicenseError("License file missing payload or signature")

    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except ValueError as e:
        raise LicenseError(f"License signature is not valid base64: {e}") from e

    public_key = _load_public_key(public_key_pem)
    try:
        public_key.verify(signature, _canonical_payload(payload))
    except InvalidSignature as e:
        raise LicenseError("License signature is invalid") from e

    try:
        lic = License(
            license_id=str(payload["license_id"]),
            customer_name=str(payload["customer_name"]),
            issued_at=datetime.fromisoformat(payload["issued_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            max_agents=_optional_int(payload.get("max_agents")),
            max_events_per_month=_optional_int(payload.get("max_events_per_month")),
            features=tuple(payload.get("features") or ()),
            schema_version=str(payload.get("schema_version", "1.0")),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise LicenseError(f"License payload is missing required fields: {e}") from e

    # Accept valid-but-expired licenses with a warning rather than
    # hard-failing — on-prem customers may be running a slightly
    # overdue box while renewal is in flight. The enforcement layer
    # decides what to do with an expired license.
    if lic.is_expired():
        log.warning(
            "license.expired",
            license_id=lic.license_id,
            expires_at=lic.expires_at.isoformat(),
        )

    return lic


def _optional_int(value: Any) -> int | None:
    """Accept explicit null (unlimited) or a non-negative int."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int in Python — reject it
        raise ValueError("max_* fields must be int or null, got bool")
    if not isinstance(value, int) or value < 0:
        raise ValueError("max_* fields must be non-negative ints or null")
    return value


def load_license(path: str, public_key_pem: str) -> License:
    """Read a license file from disk and verify it.

    Thin wrapper around ``verify_license`` so route handlers and
    startup code can share the same error semantics.
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise LicenseError(f"License file not found at {path}") from e
    except json.JSONDecodeError as e:
        raise LicenseError(f"License file is not valid JSON: {e}") from e

    return verify_license(raw, public_key_pem)
