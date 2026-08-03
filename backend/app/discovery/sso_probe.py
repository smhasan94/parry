"""SSO probe: OAuth grants -> probe events -> register rows.

aisight wrote naive datetimes here because its columns were naive. Parry's
are ``timestamptz``, so everything below stays timezone-aware end to end.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry
from app.discovery.events import NormalizedSSOEvent
from app.discovery.sso_matcher import SSOAppMatcher
from app.services.discovery_service import reconcile_ai_system

log = structlog.get_logger()

_UPSERT_PROBE_EVENT = text("""
    INSERT INTO probe_events (
        id, org_id, probe_type, raw_payload, matched_catalog_entry_id,
        dedup_key, first_seen_at, created_at, hit_count
    ) VALUES (
        :id, :org_id, :probe_type, cast(:raw_payload as jsonb), :catalog_entry_id,
        :dedup_key, :first_seen_at, now(), 1
    )
    ON CONFLICT (org_id, dedup_key) DO UPDATE SET
        hit_count = probe_events.hit_count + 1,
        processed_at = now()
    RETURNING (xmax = 0) AS inserted
""")


@dataclass
class ProcessingResult:
    processed: int = 0
    created: int = 0
    deduplicated: int = 0
    matched: int = 0
    unmatched: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


class SSOProbeProcessor:
    def __init__(self, matcher: SSOAppMatcher) -> None:
        self._matcher = matcher

    @classmethod
    async def create(cls, db: AsyncSession) -> SSOProbeProcessor:
        return cls(await SSOAppMatcher.create(db))

    async def process(
        self,
        *,
        db: AsyncSession,
        org_id: uuid.UUID,
        events: list[dict],
    ) -> ProcessingResult:
        """Entry point for raw dicts a customer pushed at us."""
        return await self.process_events(
            db=db, org_id=org_id, events=[_normalize(e) for e in events]
        )

    async def process_events(
        self,
        *,
        db: AsyncSession,
        org_id: uuid.UUID,
        events: list[NormalizedSSOEvent],
    ) -> ProcessingResult:
        """Entry point for events a provider client already normalized.

        Callers holding NormalizedSSOEvent must use this rather than
        round-tripping through ``.raw`` — that field is the provider's
        original payload, not a serialized event, so re-normalizing it
        silently blanks every field.
        """
        result = ProcessingResult(processed=len(events))

        for event in events:
            entry_id = self._matcher.match(oauth_app_id=event.oauth_app_id, app_name=event.app_name)
            if entry_id:
                result.matched += 1
            else:
                result.unmatched += 1

            status = await self._upsert_probe_event(
                db=db, org_id=org_id, event=event, catalog_entry_id=entry_id
            )
            if status == "created":
                result.created += 1
            else:
                result.deduplicated += 1

            # Only catalog-known apps enter the compliance register. An
            # unrecognized app is retained as a probe event for triage,
            # but we cannot assert what it is.
            if entry_id:
                catalog_entry = await self._get_catalog_entry(db, entry_id)
                if catalog_entry:
                    await reconcile_ai_system(
                        db=db,
                        org_id=org_id,
                        catalog_entry=catalog_entry,
                        discovery_source="sso",
                        seen_at=event.timestamp,
                    )

            result.results.append(
                {
                    "app_name": event.app_name,
                    "catalog_entry_id": str(entry_id) if entry_id else None,
                    "status": status,
                }
            )

        await db.flush()
        log.info(
            "sso_probe_processed",
            org_id=str(org_id),
            processed=result.processed,
            matched=result.matched,
            created=result.created,
        )
        return result

    async def _get_catalog_entry(
        self, db: AsyncSession, entry_id: uuid.UUID
    ) -> AICatalogEntry | None:
        result = await db.execute(select(AICatalogEntry).where(AICatalogEntry.id == entry_id))
        return result.scalar_one_or_none()

    async def _upsert_probe_event(
        self,
        *,
        db: AsyncSession,
        org_id: uuid.UUID,
        event: NormalizedSSOEvent,
        catalog_entry_id: uuid.UUID | None,
    ) -> str:
        row = (
            await db.execute(
                _UPSERT_PROBE_EVENT,
                {
                    "id": uuid.uuid4(),
                    "org_id": org_id,
                    "probe_type": "sso",
                    "raw_payload": json.dumps(event.raw),
                    "catalog_entry_id": catalog_entry_id,
                    "dedup_key": event.dedup_key(),
                    "first_seen_at": event.timestamp,
                },
            )
        ).one()
        return "created" if row.inserted else "deduplicated"


def _normalize(event: dict) -> NormalizedSSOEvent:
    return NormalizedSSOEvent(
        timestamp=_parse_timestamp(event.get("timestamp")),
        provider=event.get("provider", "unknown"),
        oauth_app_id=event.get("oauth_app_id"),
        app_name=event.get("app_name", "Unknown"),
        user_identifier=event.get("user_identifier"),
        grant_type=event.get("grant_type", "unknown"),
        status=event.get("status", "unknown"),
        raw=event,
    )


def _parse_timestamp(raw: Any) -> datetime:
    """Always returns an aware datetime — a naive value written to a
    timestamptz column silently shifts by the server's offset."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(tz=UTC)
