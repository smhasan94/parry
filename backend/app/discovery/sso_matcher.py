"""Resolve an SSO application to a catalog entry.

Built once per sync and held in memory — the catalog is a few hundred
rows and every event in a batch needs a lookup.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry

log = structlog.get_logger()


class SSOAppMatcher:
    def __init__(
        self,
        oauth_id_map: dict[str, uuid.UUID],
        name_map: dict[str, uuid.UUID],
    ) -> None:
        self._oauth_id_map = oauth_id_map
        self._name_map = name_map

    @classmethod
    async def create(cls, db: AsyncSession) -> SSOAppMatcher:
        result = await db.execute(
            select(AICatalogEntry.id, AICatalogEntry.service_name, AICatalogEntry.oauth_app_ids)
        )
        oauth_id_map: dict[str, uuid.UUID] = {}
        name_map: dict[str, uuid.UUID] = {}

        for entry_id, service_name, oauth_app_ids in result.all():
            name_map[service_name.strip().lower()] = entry_id
            for app_id in oauth_app_ids or []:
                oauth_id_map[app_id] = entry_id

        log.info(
            "sso_app_matcher_loaded",
            oauth_id_count=len(oauth_id_map),
            name_count=len(name_map),
        )
        return cls(oauth_id_map, name_map)

    def match(self, *, oauth_app_id: str | None, app_name: str) -> uuid.UUID | None:
        """OAuth client id first — it is issued by the vendor. App labels
        are free text an admin can rename, so they only break ties."""
        if oauth_app_id and (entry_id := self._oauth_id_map.get(oauth_app_id)):
            return entry_id
        return self._name_map.get(app_name.strip().lower())
