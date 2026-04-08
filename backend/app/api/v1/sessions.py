"""Session replay API.

``GET /api/v1/sessions/{session_id}`` returns a session-scoped event
timeline with detections, for the dashboard's replay view. Viewers
get metadata + previews only; admins get full prompt/response text
for forensics.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, actor_role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.services import session_service

log = structlog.get_logger()

router = APIRouter()


@router.get("/{session_id}")
async def get_session_replay(
    session_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org, actor = org_actor
    # Admins and above unlock full prompt/response content; viewers see
    # previews only so default role exposure can't exfil raw prompts.
    include_content = actor_role(actor) >= Role.ADMIN
    payload = await session_service.get_session_with_events(
        db, session_id, org.id, include_content=include_content
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload
