"""Load the vendor catalog into ``ai_catalog_entries``.

The catalog is checked-in reference data, not user input, so failures are
loud: a bad row means the seed file is wrong and needs fixing at source.
Validating here rather than at insert time lets the error name the vendor
instead of surfacing an opaque constraint violation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry, CatalogDomain

log = structlog.get_logger()

CATALOG_PATH = Path(__file__).resolve().parents[3] / "catalog" / "services.json"

_REQUIRED = ("service_name", "vendor", "category", "domains")
_VALID_TIERS = {"minimal", "limited", "high", "unacceptable"}

_SCALAR_FIELDS = (
    "trains_on_user_data",
    "data_retention_days",
    "has_enterprise_dpa",
    "soc2_certified",
    "default_risk_tier",
    "risk_tier_rationale",
    "privacy_policy_url",
    "tos_url",
)


class CatalogSeedError(Exception):
    """The catalog file is malformed."""


def load_catalog_file(path: Path | None = None) -> list[dict[str, Any]]:
    return json.loads((path or CATALOG_PATH).read_text())


def parse_catalog_entries(
    raw_entries: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[str]]]:
    """Validate and normalize seed rows into (entry_columns, domains)."""
    parsed: list[tuple[dict[str, Any], list[str]]] = []
    domain_owner: dict[str, str] = {}
    seen_services: set[tuple[str, str]] = set()

    for raw in raw_entries:
        for field in _REQUIRED:
            if not raw.get(field):
                raise CatalogSeedError(
                    f"catalog entry {raw.get('service_name', '<unnamed>')!r} "
                    f"is missing required field {field!r}"
                )

        tier = raw.get("default_risk_tier")
        if tier is not None and tier not in _VALID_TIERS:
            raise CatalogSeedError(
                f"catalog entry {raw['service_name']!r} has invalid default_risk_tier {tier!r}"
            )

        key = (raw["vendor"], raw["service_name"])
        if key in seen_services:
            raise CatalogSeedError(
                f"duplicate catalog entry {raw['service_name']!r} for vendor {raw['vendor']!r}"
            )
        seen_services.add(key)

        domains: list[str] = []
        for domain in raw["domains"]:
            normalized = domain.strip().lower()
            if normalized in domain_owner and domain_owner[normalized] != raw["service_name"]:
                raise CatalogSeedError(
                    f"domain {normalized!r} is claimed by both "
                    f"{domain_owner[normalized]!r} and {raw['service_name']!r}"
                )
            if normalized not in domains:
                domains.append(normalized)
            domain_owner[normalized] = raw["service_name"]

        entry = {
            "service_name": raw["service_name"],
            "vendor": raw["vendor"],
            "category": raw["category"],
            "foundation_models": list(raw.get("foundation_models") or []),
            "oauth_app_ids": list(raw.get("oauth_app_ids") or []),
            **{f: raw.get(f) for f in _SCALAR_FIELDS},
        }
        parsed.append((entry, domains))

    return parsed


async def seed_catalog(db: AsyncSession, path: Path | None = None) -> dict[str, int]:
    """Idempotent upsert keyed on (vendor, service_name).

    Safe to re-run on every deploy — existing entries are updated in
    place so a refreshed catalog does not orphan discovered systems that
    already point at those entry ids.
    """
    parsed = parse_catalog_entries(load_catalog_file(path))
    created = updated = 0

    for columns, domains in parsed:
        existing = (
            await db.execute(
                select(AICatalogEntry).where(
                    AICatalogEntry.vendor == columns["vendor"],
                    AICatalogEntry.service_name == columns["service_name"],
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            entry = AICatalogEntry(**columns)
            db.add(entry)
            await db.flush()
            created += 1
        else:
            for key, value in columns.items():
                setattr(existing, key, value)
            entry = existing
            updated += 1

        await _sync_domains(db, entry, domains)

    await db.flush()
    log.info("catalog_seeded", created=created, updated=updated, total=len(parsed))
    return {"created": created, "updated": updated, "total": len(parsed)}


async def _sync_domains(db: AsyncSession, entry: AICatalogEntry, domains: list[str]) -> None:
    existing = {
        d.domain
        for d in (
            await db.execute(
                select(CatalogDomain).where(CatalogDomain.catalog_entry_id == entry.id)
            )
        ).scalars()
    }
    for domain in domains:
        if domain not in existing:
            db.add(CatalogDomain(catalog_entry_id=entry.id, domain=domain))
