"""Resolve an SSO application to a catalog entry.

Built once per sync and held in memory — the catalog is a few hundred
rows and every event in a batch needs a lookup.

Three strategies, in descending confidence:

1. OAuth client id — issued by the vendor, unambiguous.
2. Exact service name.
3. Normalized containment, which is deliberately asymmetric.

Strategy 3 exists because admins rename apps and only a small minority of
catalog entries carry an OAuth id, so exact matching misses real vendors.
Its rule: the catalog name must appear *in full* within the label.

Extra words in the label are fine — "Anthropic Claude" and "Perplexity
AI" name the same products the catalog calls "Claude" and "Perplexity".
Extra words in the catalog name are not. Matching an app labelled "Figma"
to a catalog entry called "Figma AI" would assert that the org uses
Figma's AI features on the evidence of a grant saying only that they use
Figma. These rows feed a compliance register, where a wrong entry is
worse than a missing one, so that direction is refused and the app stays
an unmatched probe event for a human to triage.
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICatalogEntry

log = structlog.get_logger()

_WORD = re.compile(r"[^a-z0-9]+")

# Words that qualify a product without identifying it. Used only to
# disqualify catalog entries made entirely of them — a name like
# "Plus AI" reduces to nothing distinguishing and would otherwise be
# contained in every label in the tenant.
_NOISE = frozenset({"ai", "enterprise", "business", "pro", "plus", "cloud", "copilot", "assistant"})


def _tokens(value: str) -> list[str]:
    return [t for t in _WORD.split(value.lower()) if t]


def _label_tokens(label: str) -> set[str]:
    """Tokens of an Okta label.

    Vendor prefixes need no special handling: containment already covers
    them, since {claude} is a subset of {anthropic, claude}. An earlier
    version stripped a leading vendor name explicitly and broke the case
    where vendor and product share a name — "Perplexity AI" lost the word
    that identified it.
    """
    return set(_tokens(label))


class SSOAppMatcher:
    def __init__(
        self,
        oauth_id_map: dict[str, uuid.UUID],
        name_map: dict[str, uuid.UUID],
        normalized: list[tuple[uuid.UUID, frozenset[str]]] | None = None,
    ) -> None:
        self._oauth_id_map = oauth_id_map
        self._name_map = name_map
        # (entry_id, catalog name tokens)
        self._normalized = normalized or []

    @classmethod
    async def create(cls, db: AsyncSession) -> SSOAppMatcher:
        result = await db.execute(
            select(
                AICatalogEntry.id,
                AICatalogEntry.service_name,
                AICatalogEntry.oauth_app_ids,
            )
        )
        oauth_id_map: dict[str, uuid.UUID] = {}
        name_map: dict[str, uuid.UUID] = {}
        normalized: list[tuple[uuid.UUID, frozenset[str]]] = []

        for entry_id, service_name, oauth_app_ids in result.all():
            name_map[service_name.strip().lower()] = entry_id
            for app_id in oauth_app_ids or []:
                oauth_id_map[app_id] = entry_id

            name_tokens = frozenset(_tokens(service_name))
            # An entry named only of qualifiers ("Plus AI") is contained
            # in every label, so it is excluded from the normalized pass.
            # It can still match exactly or by OAuth id.
            if name_tokens and not name_tokens <= _NOISE:
                normalized.append((entry_id, name_tokens))

        log.info(
            "sso_app_matcher_loaded",
            oauth_id_count=len(oauth_id_map),
            name_count=len(name_map),
            normalized_count=len(normalized),
        )
        return cls(oauth_id_map, name_map, normalized)

    def match(self, *, oauth_app_id: str | None, app_name: str) -> uuid.UUID | None:
        """OAuth client id first — it is issued by the vendor. App labels
        are free text an admin can rename, so they only break ties."""
        if oauth_app_id and (entry_id := self._oauth_id_map.get(oauth_app_id)):
            return entry_id
        if entry_id := self._name_map.get(app_name.strip().lower()):
            return entry_id
        return self._match_normalized(app_name)

    def _match_normalized(self, app_name: str) -> uuid.UUID | None:
        label_tokens = _label_tokens(app_name)
        if not label_tokens:
            return None

        matches: list[uuid.UUID] = []
        for entry_id, name_tokens in self._normalized:
            # Every word of the catalog name must be present in the
            # label. The reverse is allowed; see the module docstring.
            if name_tokens <= label_tokens:
                matches.append(entry_id)

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Two plausible vendors. Guessing puts a wrong row in a
            # compliance register; returning nothing leaves a probe event
            # for a human to triage.
            log.info("sso_match_ambiguous", app_name=app_name, candidates=len(matches))
        return None
