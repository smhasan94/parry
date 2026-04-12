"""Slack interactive actions endpoint.

Receives interactive payloads from Slack when users click buttons
on incident messages. Updates incident status and responds inline.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Form, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db.models import Incident
from app.db.session import get_db
from app.services.slack_bot_service import build_action_response

log = structlog.get_logger()

router = APIRouter()

# Map Slack action IDs to incident status transitions
ACTION_STATUS_MAP = {
    "parry_acknowledge": "acknowledged",
    "parry_escalate": "escalated",
    "parry_snooze": "snoozed",
}


@router.post("/actions")
async def slack_interactive(
    payload: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle Slack interactive action payloads."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    actions = data.get("actions", [])
    if not actions:
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id", "")
    incident_id = action.get("value", "")
    user = data.get("user", {})
    user_name = user.get("real_name") or user.get("username") or "Someone"

    # Skip URL button actions — Slack sends these but they need no server response
    if action_id == "parry_view_dashboard":
        return {"ok": True}

    new_status = ACTION_STATUS_MAP.get(action_id)
    if not new_status or not incident_id:
        return {"ok": True}

    # Update incident status
    try:
        await db.execute(
            update(Incident)
            .where(Incident.id == incident_id)
            .values(status=new_status)
        )
        log.info(
            "slack.action_processed",
            action=action_id,
            incident_id=incident_id,
            user=user_name,
            new_status=new_status,
        )
    except Exception:
        log.warning("slack.action_db_error", incident_id=incident_id, exc_info=True)

    return build_action_response(action_id, incident_id, user_name)
