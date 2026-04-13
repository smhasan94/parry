import contextlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor, get_current_actor, get_current_org
from app.core.rbac import Role, require_role
from app.db.models import IncidentStatus, Org, Severity
from app.db.session import get_db
from app.schemas.incident import IncidentListResponse, IncidentResponse, IncidentUpdate
from app.services import (
    audit_service,
    incident_service,
    incident_share_service,
    plan_service,
    replay_service,
    webhook_dispatch_service,
)

router = APIRouter()


@router.get(
    "",
    response_model=IncidentListResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_incidents(
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
    severity: Severity | None = Query(None),
    status: IncidentStatus | None = Query(None),
    session_id: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> IncidentListResponse:
    incidents, next_cursor = await incident_service.list_incidents(
        db,
        org.id,
        severity=severity,
        status=status,
        session_id=session_id,
        cursor=cursor,
        limit=limit,
    )
    return IncidentListResponse(
        incidents=[IncidentResponse.model_validate(i) for i in incidents],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_incident(
    incident_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    incident = await incident_service.get_incident(db, org.id, incident_id)
    return IncidentResponse.model_validate(incident)


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> IncidentResponse:
    org, actor = org_actor

    # Capture the previous status for the audit diff
    previous = await incident_service.get_incident(db, org.id, incident_id)
    previous_status = previous.status.value

    incident = await incident_service.update_incident(
        db,
        org_id=org.id,
        incident_id=incident_id,
        **body.model_dump(exclude_unset=True),
    )

    # Audit log the change
    if body.status is not None and body.status.value != previous_status:
        await audit_service.log_action(
            db,
            org_id=org.id,
            action=f"incident.{body.status.value}",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_label=actor.label,
            resource_type="incident",
            resource_id=str(incident_id),
            details={
                "previous_status": previous_status,
                "new_status": body.status.value,
                "title": incident.title,
                "severity": incident.severity.value,
            },
        )

    # Dispatch webhook on status change
    if body.status is not None and body.status.value != previous_status:
        with contextlib.suppress(Exception):
            await webhook_dispatch_service.dispatch_event(
                db, org.id, f"incident.{body.status.value}", {
                    "incident_id": str(incident_id),
                    "title": incident.title,
                    "severity": incident.severity.value,
                    "previous_status": previous_status,
                    "new_status": body.status.value,
                },
            )

    await db.commit()
    return IncidentResponse.model_validate(incident)


@router.get(
    "/{incident_id}/replay",
)
async def get_incident_replay(
    incident_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Forensic attack chain replay for an incident.

    Reconstructs the event timeline around the trigger with smart
    windowing (top 50 most relevant events). Annotated with detections,
    permission violations, and threat intel matches.

    Content gating: viewers get 200-char previews, admins get full
    prompt/response.
    """
    from dataclasses import asdict

    from app.core.rbac import Role, actor_role

    org, actor = org_actor
    plan_service.require_feature(org, "compliance_export")

    role = actor_role(actor)
    include_content = role in (Role.ADMIN, Role.OWNER)

    replay = await replay_service.build_incident_replay(
        db, org.id, incident_id, include_content=include_content
    )

    return {
        "incident": replay.incident,
        "trigger_event_id": replay.trigger_event_id,
        "session_id": replay.session_id,
        "total_session_events": replay.total_session_events,
        "window_size": replay.window_size,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "model": e.model,
                "prompt_preview": e.prompt_preview,
                "response_preview": e.response_preview,
                **({"prompt": e.prompt, "response": e.response} if include_content else {}),
                "tool_calls": e.tool_calls,
                "token_count": e.token_count,
                "is_trigger": e.is_trigger,
                "annotations": asdict(e.annotations),
            }
            for e in replay.events
        ],
    }


@router.get(
    "/{incident_id}/share-token",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def get_share_token(
    incident_id: uuid.UUID,
    org: Org = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a shareable link token for an incident."""
    incident = await incident_service.get_incident(db, org.id, incident_id)
    token = incident_share_service.generate_share_token(str(incident.id))
    return {"token": token, "incident_id": str(incident.id)}


@router.get("/{incident_id}/share/{token}")
async def view_shared_report(
    incident_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Public shareable incident report — no auth, verified by HMAC token."""
    if not incident_share_service.verify_share_token(str(incident_id), token):
        raise HTTPException(status_code=404, detail="Invalid or expired share link")

    # Fetch incident without org scoping (public access via token)
    from sqlalchemy import select

    from app.db.models import Incident

    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Build report data
    detections = [
        {
            "detector": d.detector,
            "confidence": d.confidence,
            "reason": d.reason,
            "severity": d.severity.value,
        }
        for d in (incident.detections or [])
    ]
    report = incident_share_service.build_share_report(
        incident={
            "id": str(incident.id),
            "title": incident.title,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "created_at": incident.created_at.isoformat(),
        },
        detections=detections,
        events=[],
    )
    html = incident_share_service.render_share_html(report)
    return HTMLResponse(content=html)
