"""Parry on-prem license generator.

Two subcommands:

    uv run python -m scripts.generate_license keygen [--out-dir ./keys]
    uv run python -m scripts.generate_license issue \\
        --private-key ./keys/parry_license_ed25519 \\
        --customer "Acme Corp" \\
        --license-id lic_abc123 \\
        --max-agents 100 \\
        --max-events 5000000 \\
        --features custom_rules,compliance_export \\
        --expires 2027-01-01 \\
        --out ./licenses/acme.license

``keygen`` writes an Ed25519 keypair to two files in ``--out-dir``:

    parry_license_ed25519         (private — keep offline, never commit)
    parry_license_ed25519.pub     (public PEM — bake into on-prem images)

``issue`` signs a payload that matches ``license_service.verify_license``
and writes the JSON envelope to disk. Customers drop the resulting
file at ``/etc/parry/parry.license`` on the on-prem host.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Import the canonical encoder directly so the CLI signs bytes
# byte-for-byte identical to what the backend verifies.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.license_service import _canonical_payload  # noqa: E402


def _keygen(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    priv = Ed25519PrivateKey.generate()
    pub: Ed25519PublicKey = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path = out_dir / "parry_license_ed25519"
    pub_path = out_dir / "parry_license_ed25519.pub"
    priv_path.write_bytes(priv_pem)
    priv_path.chmod(0o600)
    pub_path.write_bytes(pub_pem)

    print(f"Wrote private key: {priv_path}")
    print(f"Wrote public key:  {pub_path}")
    print()
    print("Copy the PUBLIC key into settings.license_public_key_pem")
    print("for the on-prem image build. Never commit the private key.")
    return 0


def _issue(args: argparse.Namespace) -> int:
    priv_pem = Path(args.private_key).read_bytes()
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        print("error: private key must be Ed25519", file=sys.stderr)
        return 2

    features = (
        [f.strip() for f in args.features.split(",") if f.strip()]
        if args.features
        else []
    )

    try:
        expires_dt = datetime.fromisoformat(args.expires).replace(tzinfo=UTC)
    except ValueError as e:
        print(f"error: --expires must be ISO date/datetime: {e}", file=sys.stderr)
        return 2

    payload: dict = {
        "schema_version": "1.0",
        "license_id": args.license_id,
        "customer_name": args.customer,
        "issued_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_dt.isoformat(),
        "max_agents": None if args.max_agents < 0 else args.max_agents,
        "max_events_per_month": None if args.max_events < 0 else args.max_events,
        "features": features,
    }

    signature = priv.sign(_canonical_payload(payload))
    envelope = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2))
    out_path.chmod(0o644)

    print(f"Issued license: {out_path}")
    print(f"  customer:   {payload['customer_name']}")
    print(f"  license_id: {payload['license_id']}")
    print(f"  expires:    {payload['expires_at']}")
    print(f"  max_agents: {payload['max_agents']}")
    print(f"  max_events: {payload['max_events_per_month']}")
    print(f"  features:   {','.join(features) or '(none)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parry on-prem license tooling")
    sub = parser.add_subparsers(dest="cmd", required=True)

    kp = sub.add_parser("keygen", help="Generate a new Ed25519 license keypair")
    kp.add_argument("--out-dir", default="./keys", help="Directory to write keypair")
    kp.set_defaults(func=_keygen)

    iss = sub.add_parser("issue", help="Issue a signed license file")
    iss.add_argument("--private-key", required=True, help="Path to signing private key PEM")
    iss.add_argument("--customer", required=True, help="Customer display name")
    iss.add_argument("--license-id", required=True, help="Stable license identifier")
    iss.add_argument(
        "--max-agents",
        type=int,
        default=-1,
        help="Max agents allowed; negative = unlimited",
    )
    iss.add_argument(
        "--max-events",
        type=int,
        default=-1,
        help="Max events per month; negative = unlimited",
    )
    iss.add_argument(
        "--features",
        default="",
        help="Comma-separated feature list (custom_rules,compliance_export,...)",
    )
    iss.add_argument(
        "--expires",
        required=True,
        help="Expiry date, ISO format (2027-01-01 or 2027-01-01T00:00:00)",
    )
    iss.add_argument("--out", required=True, help="Output path for .license file")
    iss.set_defaults(func=_issue)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
