import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# ── Enums ────────────────────────────────────────────────────────


class Severity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ResponseScanMode(enum.StrEnum):
    OFF = "off"
    REDACT = "redact"
    BLOCK = "block"


class Plan(enum.StrEnum):
    """Subscription tier. Drives quota enforcement in plan_service."""

    FREE = "free"
    GROWTH = "growth"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ── Org ──────────────────────────────────────────────────────────


class Org(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    clerk_org_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # Alert config: {"slack_webhook_url": "...", "min_severity": "high"}
    alert_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Detector config: {"prompt_injection": {"trigger_threshold": 0.6, "enabled": true}, ...}
    detector_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Active blocking mode — when enabled the SDK's sync /proxy/check path
    # will reject HIGH/CRITICAL triggers before the LLM call fires.
    blocking_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Response scanning posture — off (default), redact (strip sensitive
    # patterns before returning to the agent), or block (reject the whole
    # response). Runs via the SDK's /proxy/scan-response call after the
    # LLM returns, before the SDK hands the response back to the caller.
    response_scan_mode: Mapped[ResponseScanMode] = mapped_column(
        Enum(
            ResponseScanMode,
            name="response_scan_mode",
            # StrEnum members are ("OFF", "off") etc. SQLAlchemy's
            # default is to store the member NAME ("OFF"), but the
            # Postgres enum type was hand-declared with VALUES
            # ("off") in the migration. Without values_callable
            # every insert fails with "invalid input value for
            # enum response_scan_mode: OFF".
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        default=ResponseScanMode.OFF,
        nullable=False,
        server_default=ResponseScanMode.OFF.value,
    )
    # Subscription plan — enforced by plan_service at ingest / agent
    # create. New orgs default to FREE; Stripe webhooks flip this to
    # GROWTH/PRO on subscription events.
    plan: Mapped[Plan] = mapped_column(
        Enum(
            Plan,
            name="plan",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        default=Plan.FREE,
        nullable=False,
        server_default=Plan.FREE.value,
    )
    # WorkOS organization id. When set, the org has SAML SSO enabled
    # — login via /api/v1/sso/login instead of the standard Clerk
    # flow. Optional: SaaS customers on Clerk-only remain on Clerk.
    workos_organization_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Relationships
    agents: Mapped[list["Agent"]] = relationship(back_populates="org", lazy="selectin")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="org", lazy="selectin")
    policies: Mapped[list["Policy"]] = relationship(back_populates="org", lazy="selectin")


# ── API Key ──────────────────────────────────────────────────────


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped["Org"] = relationship(back_populates="api_keys")


# ── Agent ────────────────────────────────────────────────────────


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    baseline: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_agent_org_name"),)

    org: Mapped["Org"] = relationship(back_populates="agents")
    sessions: Mapped[list["AgentSession"]] = relationship(back_populates="agent", lazy="selectin")


# ── Session ──────────────────────────────────────────────────────


class AgentSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_sessions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="sessions")
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="session", lazy="selectin")


# ── Event (TimescaleDB hypertable) ───────────────────────────────


class AgentEvent(Base, TimestampMixin):
    """TimescaleDB hypertable — composite PK (id, timestamp) required for partitioning."""

    __tablename__ = "agent_events"
    __table_args__ = (PrimaryKeyConstraint("id", "timestamp"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=func.gen_random_uuid(), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 8), default=0, nullable=False, server_default="0"
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    session: Mapped["AgentSession | None"] = relationship(back_populates="events")


# ── Detection ────────────────────────────────────────────────────


class Detection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "detections"

    # No FK to agent_events — TimescaleDB hypertables don't support inbound FKs.
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    detector: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(
            Severity,
            name="severity",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    incident: Mapped["Incident | None"] = relationship(back_populates="detections")


# ── Incident ─────────────────────────────────────────────────────


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "incidents"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(
            Severity,
            name="severity",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(
            IncidentStatus,
            name="incidentstatus",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        default=IncidentStatus.OPEN,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    detections: Mapped[list["Detection"]] = relationship(back_populates="incident", lazy="selectin")


# ── Policy ───────────────────────────────────────────────────────


class Policy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "policies"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Policy rules stored as JSONB
    allowed_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blocked_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    allowed_domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blocked_domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    max_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forbidden_patterns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    custom_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    org: Mapped["Org"] = relationship(back_populates="policies")


# ── Audit Log ────────────────────────────────────────────────────


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Tamper-evident record of who did what.

    Append-only — no updates or deletes from application code. Designed for
    compliance auditing (SOC 2, ISO 27001) and incident forensics.
    """

    __tablename__ = "audit_log"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Actor identity (denormalized so the record survives user deletion)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user|api_key|system
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # What happened
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Optional structured payload (before/after diff, IP, user-agent, etc.)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# ── Red Team ─────────────────────────────────────────────────────


class RedTeamRun(Base, UUIDPrimaryKeyMixin):
    """One execution of the bundled attack corpus against an agent.

    Has its own storage — never references AgentEvent or Detection so
    a sandbox replay can never contaminate real telemetry.
    """

    __tablename__ = "red_team_runs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # sandbox|live
    status: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # queued|running|completed|failed
    total_attacks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(1), nullable=True)
    category_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("mode IN ('sandbox', 'live')", name="ck_red_team_runs_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_red_team_runs_status",
        ),
    )

    results: Mapped[list["RedTeamResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RedTeamResult(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "red_team_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("red_team_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attack_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attack_category: Mapped[str] = mapped_column(String(64), nullable=False)
    attack_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detectors_fired: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    max_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["RedTeamRun"] = relationship(back_populates="results")


# ── MCP ──────────────────────────────────────────────────────────


class MCPServer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Model Context Protocol server an org's agent has connected to.

    One row per unique ``(org_id, server_uri)``. Each row caches the
    canonical manifest + a sha256 hash for drift detection, plus a
    trust level that gates whether `SentinelMCPClient` will allow
    subsequent tool calls through.
    """

    __tablename__ = "mcp_servers"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    server_uri: Mapped[str] = mapped_column(Text, nullable=False)
    server_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trust_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="observed"
    )
    reputation: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    hash_history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("org_id", "server_uri", name="uq_mcp_servers_org_uri"),
        CheckConstraint(
            "trust_level IN ('observed', 'trusted', 'suspicious', 'blocked')",
            name="ck_mcp_servers_trust_level",
        ),
        CheckConstraint(
            "reputation BETWEEN 0 AND 100",
            name="ck_mcp_servers_reputation",
        ),
    )


# ── Budget ──────────────────────────────────────────────────────


class AgentBudget(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-agent (or org-wide default) spend cap.

    When ``agent_id`` is NULL the budget acts as the org-wide default
    for any agent that doesn't have its own row. Period is one of
    hour / day / month, enforced via Redis counters in budget_service.
    """

    __tablename__ = "agent_budgets"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    period: Mapped[str] = mapped_column(Text, nullable=False)
    cap_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    alert_at_pcts: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[75, 90, 100]"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "agent_id", "period", name="uq_agent_budgets_org_agent_period"),
        CheckConstraint("period IN ('hour', 'day', 'month')", name="ck_agent_budgets_period"),
        CheckConstraint("cap_usd > 0", name="ck_agent_budgets_cap_positive"),
    )


# ── EU AI Act Compliance ────────────────────────────────────────


class AISystem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An AI system in the Article 26 deployer register.

    Maps to one or more Parry agents via ``agent_ids``. Carries risk
    classification per Annex III and tracks FRIA obligation status.
    """

    __tablename__ = "ai_systems"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    intended_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    deployer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fria_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    fria_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_required", server_default="not_required"
    )
    agent_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    annex_iii_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_ai_systems_risk_level",
        ),
        CheckConstraint(
            "fria_status IN ('not_required', 'missing', 'draft', 'approved', 'stale')",
            name="ck_ai_systems_fria_status",
        ),
    )

    suppliers: Mapped[list["AISystemSupplier"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )
    fria_documents: Mapped[list["FRIADocument"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )


class AISystemSupplier(Base, UUIDPrimaryKeyMixin):
    """Auto-populated record of a model provider used by an AI system.

    Upserted daily from agent_events by the supplier refresh task.
    """

    __tablename__ = "ai_system_suppliers"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="CASCADE"), nullable=False
    )
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "system_id", "supplier_name", "model_id",
            name="uq_ai_system_suppliers_system_supplier_model",
        ),
    )

    system: Mapped["AISystem"] = relationship(back_populates="suppliers")


class FRIADocument(Base, UUIDPrimaryKeyMixin):
    """A versioned Fundamental Rights Impact Assessment document.

    Draft → approved (with PDF snapshot) → archived. Approved FRIAs
    auto-stale after 12 months via the compliance refresh task.
    """

    __tablename__ = "fria_documents"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    generated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("system_id", "version", name="uq_fria_documents_system_version"),
        CheckConstraint(
            "status IN ('draft', 'approved', 'archived')",
            name="ck_fria_documents_status",
        ),
    )

    system: Mapped["AISystem"] = relationship(back_populates="fria_documents")


class SeriousIncident(Base, UUIDPrimaryKeyMixin):
    """Article 73 serious incident report.

    Created from a CRITICAL Parry incident, pre-filled with incident
    data, 15-day deadline tracked via ``deadline_at``.
    """

    __tablename__ = "serious_incidents"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id"), nullable=True
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_to_authority_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    authority_jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    report_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "incident_id", "report_version",
            name="uq_serious_incidents_incident_version",
        ),
    )


# ── Agent Permissions ───────────────────────────────────────────


class AgentPermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-agent (or org-wide default) tool permission boundaries.

    When ``agent_id`` is NULL the record acts as the org-wide default.
    Resolution order: agent-specific → org default → allow-all.

    ``mode``:
    - ``enforcing`` — violations block the call (independent of blocking_enabled)
    - ``dry_run`` — violations logged as detections but calls pass through
    - ``disabled`` — no permission checking

    ``default_action``:
    - ``allow`` — unlisted tools are permitted (blocklist mode)
    - ``deny`` — only listed tools are permitted (allowlist mode)
    """

    __tablename__ = "agent_permissions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="disabled", server_default="disabled"
    )
    default_action: Mapped[str] = mapped_column(
        String(8), nullable=False, default="allow", server_default="allow"
    )
    allowed_tools: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    blocked_tools: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "agent_id", name="uq_agent_permissions_org_agent"),
        CheckConstraint(
            "mode IN ('enforcing', 'dry_run', 'disabled')",
            name="ck_agent_permissions_mode",
        ),
        CheckConstraint(
            "default_action IN ('allow', 'deny')",
            name="ck_agent_permissions_default_action",
        ),
    )
