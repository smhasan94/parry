"""Normalized shapes every probe reduces its provider payload to."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass
class NormalizedSSOEvent:
    timestamp: datetime
    provider: str
    oauth_app_id: str | None
    app_name: str
    user_identifier: str | None
    grant_type: str
    status: str
    raw: dict

    def dedup_key(self) -> str:
        """SHA-256 of (app, user).

        Deliberately time-free: an OAuth grant is a standing permission,
        not a point-in-time event. Re-syncing Okta every hour must bump
        ``hit_count`` on one row rather than accrete a row per sync.
        """
        app_id = self.oauth_app_id or self.app_name.strip().lower()
        identifier = self.user_identifier or "unknown"
        return hashlib.sha256(f"sso|{app_id}|{identifier}".encode()).hexdigest()
