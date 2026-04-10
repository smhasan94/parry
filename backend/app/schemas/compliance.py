import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.base import ParrySchema


# ── AI System ───────────────────────────────────────────────────

RiskLevel = Literal["minimal", "limited", "high", "unacceptable"]
FRIAStatus = Literal["not_required", "missing", "draft", "approved", "stale"]


class AISystemCreate(ParrySchema):
    name: str
    description: str | None = None
    risk_level: RiskLevel
    intended_purpose: str
    deployer_name: str | None = None
    provider_name: str | None = None
    provider_contact: str | None = None
    deployment_date: date | None = None
    agent_ids: list[uuid.UUID] = Field(default_factory=list)
    annex_iii_category: str | None = None
    jurisdiction: str | None = None
    metadata: dict[str, Any] | None = None


class AISystemUpdate(ParrySchema):
    name: str | None = None
    description: str | None = None
    risk_level: RiskLevel | None = None
    intended_purpose: str | None = None
    deployer_name: str | None = None
    provider_name: str | None = None
    provider_contact: str | None = None
    deployment_date: date | None = None
    retired_date: date | None = None
    agent_ids: list[uuid.UUID] | None = None
    annex_iii_category: str | None = None
    jurisdiction: str | None = None
    metadata: dict[str, Any] | None = None


class AISystemResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None
    risk_level: str
    intended_purpose: str
    deployer_name: str | None = None
    provider_name: str | None = None
    provider_contact: str | None = None
    deployment_date: date | None = None
    retired_date: date | None = None
    fria_required: bool
    fria_status: str
    agent_ids: list[uuid.UUID]
    annex_iii_category: str | None = None
    jurisdiction: str | None = None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Supplier ────────────────────────────────────────────────────


class SupplierResponse(ParrySchema):
    id: uuid.UUID
    system_id: uuid.UUID
    supplier_name: str
    model_id: str
    model_version: str | None = None
    first_used_at: datetime
    last_used_at: datetime
    event_count: int
    jurisdiction: str | None = None
    provider_url: str | None = None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")


# ── FRIA ────────────────────────────────────────────────────────


class FRIACreateRequest(ParrySchema):
    """Kick off a new FRIA draft for a system."""

    generated_by: str | None = None


class FRIAUpdateRequest(ParrySchema):
    """Merge user-filled fields into a draft FRIA."""

    content: dict[str, Any]


class FRIAApproveRequest(ParrySchema):
    approver_title: str | None = None


class FRIAResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    system_id: uuid.UUID
    version: int
    status: str
    content: dict[str, Any]
    generated_at: datetime
    generated_by: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    approver_title: str | None = None
    next_review_date: date | None = None


# ── Serious Incident ────────────────────────────────────────────


class SeriousIncidentCreateRequest(ParrySchema):
    """Create a serious incident report draft from a Parry incident."""

    system_id: uuid.UUID | None = None
    created_by: str | None = None


class SeriousIncidentUpdateRequest(ParrySchema):
    report_content: dict[str, Any] | None = None
    authority_jurisdiction: str | None = None
    system_id: uuid.UUID | None = None


class SeriousIncidentResponse(ParrySchema):
    id: uuid.UUID
    org_id: uuid.UUID
    incident_id: uuid.UUID
    system_id: uuid.UUID | None = None
    deadline_at: datetime
    reported_to_authority_at: datetime | None = None
    authority_jurisdiction: str | None = None
    report_version: int
    report_content: dict[str, Any]
    created_at: datetime
    created_by: str | None = None
    days_remaining: int | None = None


# ── Compliance Posture ──────────────────────────────────────────

ObligationStatus = Literal["green", "yellow", "red", "na"]


class ObligationResponse(ParrySchema):
    id: str
    article: str
    title: str
    status: ObligationStatus
    evidence: dict[str, Any]
    remediation: str | None = None


class PostureResponse(ParrySchema):
    overall_status: ObligationStatus
    obligations: list[ObligationResponse]


# ── Auditor Bundle ──────────────────────────────────────────────


class AuditorBundleRequest(ParrySchema):
    """Request generation of an auditor bundle ZIP."""

    period_start: date | None = None
    period_end: date | None = None


class AuditorBundleStatusResponse(ParrySchema):
    job_id: str
    status: str  # queued|running|completed|failed
    download_url: str | None = None
