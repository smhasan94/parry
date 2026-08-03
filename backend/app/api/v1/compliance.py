"""EU AI Act Article 26 compliance routes.

Covers: posture dashboard, AI system register CRUD, FRIA lifecycle,
serious incident reporting, and auditor bundle generation.
"""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import Actor
from app.core.rbac import Role, require_role
from app.db.models import Org
from app.db.session import get_db
from app.schemas.compliance import (
    AISystemCreate,
    AISystemResponse,
    AISystemUpdate,
    AuditorBundleRequest,
    AuditorBundleStatusResponse,
    ClassificationRejectRequest,
    FRIAApproveRequest,
    FRIACreateRequest,
    FRIAResponse,
    FRIAUpdateRequest,
    ObligationResponse,
    PostureResponse,
    RiskClassificationResponse,
    SeriousIncidentCreateRequest,
    SeriousIncidentResponse,
    SeriousIncidentUpdateRequest,
    SupplierResponse,
)
from app.services import (
    ai_system_service,
    audit_service,
    classification_service,
    fria_service,
    plan_service,
    serious_incident_service,
)
from app.services.compliance_posture_service import (
    get_posture,
    overall_status,
)

log = structlog.get_logger()
router = APIRouter()


# ── Posture ─────────────────────────────────────────────────────


@router.get(
    "/posture",
    response_model=PostureResponse,
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def get_compliance_posture(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> PostureResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "compliance_posture")
    obligations = await get_posture(db, org.id)
    return PostureResponse(
        overall_status=overall_status(obligations),
        obligations=[
            ObligationResponse(
                id=o.id,
                article=o.article,
                title=o.title,
                status=o.status,
                evidence=o.evidence,
                remediation=o.remediation,
            )
            for o in obligations
        ],
    )


# ── AI Systems CRUD ────────────────────────────────────────────


@router.get(
    "/systems",
    response_model=list[AISystemResponse],
)
async def list_systems(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    risk_level: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> list[AISystemResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "ai_system_register")
    systems, _ = await ai_system_service.list_systems(
        db, org.id, risk_level=risk_level, cursor=cursor, limit=limit
    )
    return [AISystemResponse.model_validate(s) for s in systems]


@router.post(
    "/systems",
    response_model=AISystemResponse,
    status_code=201,
)
async def create_system(
    body: AISystemCreate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AISystemResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "ai_system_register")
    system = await ai_system_service.create_system(db, org.id, **body.model_dump())
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="ai_system.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="ai_system",
        resource_id=str(system.id),
        details={"name": body.name, "risk_level": body.risk_level},
    )
    await db.commit()
    return AISystemResponse.model_validate(system)


@router.get(
    "/systems/{system_id}",
    response_model=AISystemResponse,
)
async def get_system(
    system_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> AISystemResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "ai_system_register")
    system = await ai_system_service.get_system(db, org.id, system_id)
    return AISystemResponse.model_validate(system)


@router.put(
    "/systems/{system_id}",
    response_model=AISystemResponse,
)
async def update_system(
    system_id: uuid.UUID,
    body: AISystemUpdate,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AISystemResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "ai_system_register")
    system = await ai_system_service.update_system(
        db, org.id, system_id, **body.model_dump(exclude_unset=True)
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="ai_system.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="ai_system",
        resource_id=str(system_id),
    )
    await db.commit()
    return AISystemResponse.model_validate(system)


@router.delete(
    "/systems/{system_id}",
    status_code=204,
)
async def delete_system(
    system_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    org, actor = org_actor
    plan_service.require_feature(org, "ai_system_register")
    await ai_system_service.delete_system(db, org.id, system_id)
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="ai_system.deleted",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="ai_system",
        resource_id=str(system_id),
    )
    await db.commit()


# ── Suppliers ───────────────────────────────────────────────────


@router.get(
    "/systems/{system_id}/suppliers",
    response_model=list[SupplierResponse],
)
async def list_suppliers(
    system_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[SupplierResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "ai_system_register")
    # Verify system belongs to org
    await ai_system_service.get_system(db, org.id, system_id)
    suppliers = await ai_system_service.list_suppliers(db, system_id)
    return [SupplierResponse.model_validate(s) for s in suppliers]


# ── FRIA ────────────────────────────────────────────────────────


@router.get(
    "/systems/{system_id}/fria",
    response_model=list[FRIAResponse],
)
async def list_system_frias(
    system_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> list[FRIAResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "fria_generator")
    await ai_system_service.get_system(db, org.id, system_id)
    frias = await fria_service.list_frias(db, org.id, system_id=system_id)
    return [FRIAResponse.model_validate(f) for f in frias]


@router.post(
    "/systems/{system_id}/fria",
    response_model=FRIAResponse,
    status_code=201,
)
async def create_fria(
    system_id: uuid.UUID,
    body: FRIACreateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> FRIAResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "fria_generator")
    doc = await fria_service.generate_fria(
        db, org.id, system_id, generated_by=body.generated_by or actor.label
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="fria.generated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="fria_document",
        resource_id=str(doc.id),
        details={"system_id": str(system_id), "version": doc.version},
    )
    await db.commit()
    return FRIAResponse.model_validate(doc)


@router.get(
    "/fria/{fria_id}",
    response_model=FRIAResponse,
)
async def get_fria(
    fria_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> FRIAResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "fria_generator")
    doc = await fria_service.get_fria(db, org.id, fria_id)
    return FRIAResponse.model_validate(doc)


@router.put(
    "/fria/{fria_id}",
    response_model=FRIAResponse,
)
async def update_fria(
    fria_id: uuid.UUID,
    body: FRIAUpdateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> FRIAResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "fria_generator")
    doc = await fria_service.update_fria(db, org.id, fria_id, body.content)
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="fria.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="fria_document",
        resource_id=str(fria_id),
    )
    await db.commit()
    return FRIAResponse.model_validate(doc)


@router.post(
    "/fria/{fria_id}/approve",
    response_model=FRIAResponse,
)
async def approve_fria(
    fria_id: uuid.UUID,
    body: FRIAApproveRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> FRIAResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "fria_generator")
    doc = await fria_service.approve_fria(
        db,
        org.id,
        fria_id,
        approved_by=actor.label or str(actor.actor_id),
        approver_title=body.approver_title,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="fria.approved",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="fria_document",
        resource_id=str(fria_id),
        obligation_ids=["art_27_fria"],
    )
    await db.commit()
    return FRIAResponse.model_validate(doc)


@router.get(
    "/fria/{fria_id}/pdf",
)
async def download_fria_pdf(
    fria_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from fastapi.responses import Response

    org, _ = org_actor
    plan_service.require_feature(org, "fria_generator")
    doc = await fria_service.get_fria(db, org.id, fria_id)
    if doc.pdf_bytes is None:
        raise HTTPException(
            status_code=404, detail="PDF not yet generated (approve the FRIA first)"
        )
    return Response(
        content=doc.pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="fria-v{doc.version}.pdf"'},
    )


# ── Serious Incidents ───────────────────────────────────────────


@router.get(
    "/serious-incidents",
    response_model=list[SeriousIncidentResponse],
)
async def list_serious_incidents(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    unreported_only: bool = Query(False),
) -> list[SeriousIncidentResponse]:
    org, _ = org_actor
    plan_service.require_feature(org, "serious_incident_reporting")
    reports = await serious_incident_service.list_reports(
        db, org.id, unreported_only=unreported_only
    )
    result = []
    for r in reports:
        resp = SeriousIncidentResponse.model_validate(r)
        resp.days_remaining = serious_incident_service.days_remaining(r)
        result.append(resp)
    return result


@router.post(
    "/incidents/{incident_id}/serious-report",
    response_model=SeriousIncidentResponse,
    status_code=201,
)
async def create_serious_report(
    incident_id: uuid.UUID,
    body: SeriousIncidentCreateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SeriousIncidentResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "serious_incident_reporting")
    report = await serious_incident_service.create_draft(
        db,
        org.id,
        incident_id,
        system_id=body.system_id,
        created_by=body.created_by or actor.label,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="serious_incident.created",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="serious_incident",
        resource_id=str(report.id),
        details={"incident_id": str(incident_id)},
    )
    await db.commit()
    resp = SeriousIncidentResponse.model_validate(report)
    resp.days_remaining = serious_incident_service.days_remaining(report)
    return resp


@router.get(
    "/serious-incidents/{report_id}",
    response_model=SeriousIncidentResponse,
)
async def get_serious_report(
    report_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> SeriousIncidentResponse:
    org, _ = org_actor
    plan_service.require_feature(org, "serious_incident_reporting")
    report = await serious_incident_service.get_report(db, org.id, report_id)
    resp = SeriousIncidentResponse.model_validate(report)
    resp.days_remaining = serious_incident_service.days_remaining(report)
    return resp


@router.put(
    "/serious-incidents/{report_id}",
    response_model=SeriousIncidentResponse,
)
async def update_serious_report(
    report_id: uuid.UUID,
    body: SeriousIncidentUpdateRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SeriousIncidentResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "serious_incident_reporting")
    report = await serious_incident_service.update_draft(
        db,
        org.id,
        report_id,
        report_content=body.report_content,
        authority_jurisdiction=body.authority_jurisdiction,
        system_id=body.system_id,
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="serious_incident.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="serious_incident",
        resource_id=str(report_id),
    )
    await db.commit()
    resp = SeriousIncidentResponse.model_validate(report)
    resp.days_remaining = serious_incident_service.days_remaining(report)
    return resp


@router.post(
    "/serious-incidents/{report_id}/finalize",
    response_model=SeriousIncidentResponse,
)
async def finalize_serious_report(
    report_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> SeriousIncidentResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "serious_incident_reporting")
    report = await serious_incident_service.finalize(
        db, org.id, report_id, finalized_by=actor.label or str(actor.actor_id)
    )
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="serious_incident.finalized",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="serious_incident",
        resource_id=str(report_id),
        obligation_ids=["art_73_serious_incidents"],
    )
    await db.commit()
    resp = SeriousIncidentResponse.model_validate(report)
    resp.days_remaining = 0
    return resp


# ── Auditor Bundle ──────────────────────────────────────────────


@router.post(
    "/auditor-bundle",
    response_model=AuditorBundleStatusResponse,
    status_code=202,
)
async def generate_auditor_bundle(
    body: AuditorBundleRequest,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> AuditorBundleStatusResponse:
    org, actor = org_actor
    plan_service.require_feature(org, "auditor_bundle")

    # Generate a job ID and enqueue
    job_id = str(uuid.uuid4())
    await audit_service.log_action(
        db,
        org_id=org.id,
        action="auditor_bundle.requested",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        details={
            "job_id": job_id,
            "period_start": str(body.period_start) if body.period_start else None,
            "period_end": str(body.period_end) if body.period_end else None,
        },
    )
    await db.commit()

    try:
        from app.workers.auditor_bundle_task import generate_bundle

        generate_bundle.delay(
            job_id,
            str(org.id),
            str(body.period_start) if body.period_start else None,
            str(body.period_end) if body.period_end else None,
        )
    except Exception:
        log.warning("auditor_bundle.dispatch_failed", job_id=job_id, exc_info=True)

    return AuditorBundleStatusResponse(
        job_id=job_id,
        status="queued",
    )


# ── Risk Classification Review ──────────────────────────────────


@router.get(
    "/classifications",
    response_model=list[RiskClassificationResponse],
)
async def list_pending_classifications(
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[RiskClassificationResponse]:
    """The review queue — proposed tiers nobody has ruled on yet."""
    org, _ = org_actor
    pending = await classification_service.list_pending(db, org_id=org.id, limit=limit)
    return [RiskClassificationResponse.model_validate(c) for c in pending]


@router.post(
    "/classifications/{classification_id}/approve",
    response_model=RiskClassificationResponse,
)
async def approve_classification(
    classification_id: uuid.UUID,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> RiskClassificationResponse:
    """Ratify a proposed tier, making it the system's tier of record.

    Promotes the tier onto the AI system and re-derives the Article 27
    FRIA obligation, so a high-risk approval immediately shows up as an
    outstanding FRIA in the compliance posture.
    """
    org, actor = org_actor
    approved = await classification_service.approve(
        db,
        org_id=org.id,
        classification_id=classification_id,
        reviewed_by=actor.actor_id or "unknown",
    )
    await db.commit()
    return RiskClassificationResponse.model_validate(approved)


@router.post(
    "/classifications/{classification_id}/reject",
    response_model=RiskClassificationResponse,
)
async def reject_classification(
    classification_id: uuid.UUID,
    body: ClassificationRejectRequest | None = None,
    org_actor: tuple[Org, Actor] = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> RiskClassificationResponse:
    """Decline a proposed tier. The system keeps whatever tier it had."""
    org, actor = org_actor
    rejected = await classification_service.reject(
        db,
        org_id=org.id,
        classification_id=classification_id,
        reviewed_by=actor.actor_id or "unknown",
        reason=body.reason if body else None,
    )
    await db.commit()
    return RiskClassificationResponse.model_validate(rejected)
