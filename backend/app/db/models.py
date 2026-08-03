import enum
import uuid
from datetime import date, datetime
from typing import Any

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
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    # Alert config: {"slack_webhook_url": "...", "min_severity": "high"}
    alert_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Detector config: {"prompt_injection": {"trigger_threshold": 0.6, "enabled": true}, ...}
    detector_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    # Cross-org threat intelligence sharing. When True (default),
    # this org's high-confidence detections contribute anonymized
    # pattern signatures to the shared threat feed.
    threat_intel_sharing: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    # Relationships
    agents: Mapped[list["Agent"]] = relationship(back_populates="org", lazy="selectin")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="org", lazy="selectin")
    policies: Mapped[list["Policy"]] = relationship(back_populates="org", lazy="selectin")


# ── Agent Group ─────────────────────────────────────────────────


class AgentGroup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Named group of agents within an org.

    Groups inherit the org-wide default permission unless a
    group-specific permission record exists (agent_permissions with
    agent_id matching a synthetic group key). An agent belongs to
    at most one group.
    """

    __tablename__ = "agent_groups"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_agent_groups_org_name"),
    )

    agents: Mapped[list["Agent"]] = relationship(back_populates="group", lazy="selectin")


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
    baseline: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_groups.id", ondelete="SET NULL"), nullable=True
    )
    badge_public: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_agent_org_name"),)

    org: Mapped["Org"] = relationship(back_populates="agents")
    group: Mapped["AgentGroup | None"] = relationship(back_populates="agents")
    sessions: Mapped[list["AgentSession"]] = relationship(back_populates="agent", lazy="selectin")


# ── Session ──────────────────────────────────────────────────────


class AgentSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_sessions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

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
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 8), default=0, nullable=False, server_default="0"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

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
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

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
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

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
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    blocked_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    allowed_domains: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    blocked_domains: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    max_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forbidden_patterns: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    custom_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

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
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    category_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    detectors_fired: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
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
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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
    hash_history: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

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
    alert_at_pcts: Mapped[list[int]] = mapped_column(
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

    Arrives three ways, distinguished by ``origin``: declared by a human,
    discovered by a probe, or observed via SDK traffic. Maps to zero or
    more Parry agents via ``agent_ids`` — a discovered system with an
    empty ``agent_ids`` is shadow AI, present but unmonitored.

    Carries risk classification per Annex III and tracks FRIA status.
    """

    __tablename__ = "ai_systems"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'unclassified' is the arrival state for discovered systems — a probe
    # cannot infer an Annex III tier from an OAuth grant.
    risk_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unclassified", server_default="unclassified"
    )
    # Nullable for the same reason: probes cannot infer intended purpose.
    intended_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default="declared", server_default="declared"
    )
    discovery_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    catalog_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_catalog_entries.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    deployment_context: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('unclassified', 'minimal', 'limited', 'high', 'unacceptable')",
            name="ck_ai_systems_risk_level",
        ),
        CheckConstraint(
            "fria_status IN ('not_required', 'missing', 'draft', 'approved', 'stale')",
            name="ck_ai_systems_fria_status",
        ),
        CheckConstraint(
            "origin IN ('declared', 'discovered', 'instrumented')",
            name="ck_ai_systems_origin",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'blocked', 'retired')",
            name="ck_ai_systems_status",
        ),
    )

    suppliers: Mapped[list["AISystemSupplier"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )
    fria_documents: Mapped[list["FRIADocument"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", lazy="selectin"
    )
    classifications: Mapped[list["RiskClassification"]] = relationship(
        back_populates="system", cascade="all, delete-orphan"
    )
    catalog_entry: Mapped["AICatalogEntry | None"] = relationship()


class AISystemSupplier(Base, UUIDPrimaryKeyMixin):
    """Auto-populated record of a model provider used by an AI system.

    Upserted daily from agent_events by the supplier refresh task.
    """

    __tablename__ = "ai_system_suppliers"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="CASCADE"), nullable=False
    )
    # 'observed' rows come from agent_events; 'declared' rows come from the
    # vendor catalog and have no usage timestamps until traffic confirms them.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="observed", server_default="observed"
    )
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "system_id", "supplier_name", "model_id", "source",
            name="uq_ai_system_suppliers_system_supplier_model_source",
        ),
        CheckConstraint(
            "source IN ('observed', 'declared')", name="ck_ai_system_suppliers_source"
        ),
    )

    system: Mapped["AISystem"] = relationship(back_populates="suppliers")


# ── Discovery: vendor catalog ────────────────────────────────────


class AICatalogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A known third-party AI service.

    Global, NOT org-scoped — "what is Notion AI, which foundation models
    does it use, does it train on customer data" is the same answer for
    every tenant. Seeded from ``catalog/services.json``.
    """

    __tablename__ = "ai_catalog_entries"

    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    foundation_models: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    oauth_app_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    trains_on_user_data: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_enterprise_dpa: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    soc2_certified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    default_risk_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_tier_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy_policy_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    tos_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("vendor", "service_name", name="uq_catalog_vendor_service"),
        CheckConstraint(
            "default_risk_tier IS NULL OR default_risk_tier IN "
            "('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_catalog_default_risk_tier",
        ),
    )

    domains: Mapped[list["CatalogDomain"]] = relationship(
        back_populates="catalog_entry", cascade="all, delete-orphan", lazy="selectin"
    )


class CatalogDomain(Base, UUIDPrimaryKeyMixin):
    """A domain owned by a catalog entry. Globally unique — one domain
    cannot belong to two vendors, which is what makes domain → vendor
    resolution a single indexed lookup for the network probe."""

    __tablename__ = "catalog_domains"

    catalog_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_catalog_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (UniqueConstraint("domain", name="uq_catalog_domains_domain"),)

    catalog_entry: Mapped["AICatalogEntry"] = relationship(back_populates="domains")


# ── Discovery: probes ────────────────────────────────────────────


class ProbeEvent(Base, UUIDPrimaryKeyMixin):
    """One raw discovery signal, deduplicated by ``dedup_key``.

    SSO grants are persistent, so their dedup key has no time component —
    re-syncing Okta bumps ``hit_count`` rather than inserting duplicates.
    """

    __tablename__ = "probe_events"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="SET NULL"), nullable=True
    )
    probe_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    matched_catalog_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_catalog_entries.id", ondelete="SET NULL"), nullable=True
    )
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("org_id", "dedup_key", name="uq_probe_events_org_dedup"),
        CheckConstraint(
            "probe_type IN ('network', 'sso', 'browser')", name="ck_probe_events_type"
        ),
    )


class ProbeCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Connection config for one discovery probe.

    ``encrypted_secret`` is ciphertext at rest — never expose it in a
    response schema.
    """

    __tablename__ = "probe_credentials"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    probe_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    encrypted_secret: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "probe_type IN ('network', 'sso', 'browser')", name="ck_probe_credentials_type"
        ),
    )


# ── Discovery: classification ────────────────────────────────────


class RiskClassification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Classification history behind ``ai_systems.risk_level``.

    The system row holds the current effective tier; this table holds how
    it was reached — catalog default, LLM draft, or human override — with
    the reasoning and evidence that justify it to an auditor.
    """

    __tablename__ = "risk_classifications"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_urls: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Clerk user id, not an FK — Parry has no users table.
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending_review", server_default="pending_review"
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('catalog', 'llm_draft', 'human_override')",
            name="ck_risk_classifications_source",
        ),
        CheckConstraint(
            "risk_tier IN ('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_risk_classifications_tier",
        ),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')",
            name="ck_risk_classifications_status",
        ),
    )

    system: Mapped["AISystem"] = relationship(back_populates="classifications")


class ConformityAssessment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Article 43 conformity assessment. Distinct obligation from the
    Article 27 FRIA in ``fria_documents`` — both apply."""

    __tablename__ = "conformity_assessments"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_systems.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_started", server_default="not_started"
    )
    template_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint(
            "status IN ('not_started', 'in_review', 'compliant', 'non_compliant')",
            name="ck_conformity_assessments_status",
        ),
    )


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
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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
    report_content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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
    allowed_tools: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    blocked_tools: Mapped[list[str]] = mapped_column(
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


# ── Threat Intelligence ─────────────────────────────────────────


class ThreatIndicator(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An anonymized attack pattern aggregated across multiple orgs.

    Indicators start unpromoted. Once ``org_count`` reaches 3, the
    indicator is promoted (``promoted_at`` set) and the
    ``ThreatIntelDetector`` starts matching against it. ``score``
    decays daily; indicators drop out of the active feed when score
    falls below 0.3 and are archived below 0.1.
    """

    __tablename__ = "threat_indicators"

    pattern_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    detector_source: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    sighting_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    org_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sample_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sightings: Mapped[list["ThreatSighting"]] = relationship(
        back_populates="indicator", cascade="all, delete-orphan", lazy="selectin"
    )


class ThreatSighting(Base, UUIDPrimaryKeyMixin):
    """Records that a specific org observed a threat indicator.

    One row per (indicator, org) pair — tracks distinct org count,
    not total event count. Updated on repeat sightings.
    """

    __tablename__ = "threat_sightings"

    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threat_indicators.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "indicator_id", "org_id",
            name="uq_threat_sightings_indicator_org",
        ),
    )

    indicator: Mapped["ThreatIndicator"] = relationship(back_populates="sightings")


# ── Webhook Subscriptions ───────────────────────────────────────


class WebhookEndpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Customer-managed webhook subscription.

    Receives HTTP POST notifications for configured event types.
    Secret is used for HMAC-SHA256 signing of the payload so the
    customer can verify authenticity.
    """

    __tablename__ = "webhook_endpoints"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan", lazy="noload"
    )


class WebhookDelivery(Base, UUIDPrimaryKeyMixin):
    """Record of a single webhook delivery attempt."""

    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    endpoint: Mapped["WebhookEndpoint"] = relationship(back_populates="deliveries")


# ── Scheduled Reports ───────────────────────────────────────────


class ScheduledReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Recurring security report delivered via email.

    ``schedule``: weekly (Monday 08:00 UTC) or monthly (1st, 08:00 UTC).
    ``report_type``: security_summary (detections, incidents, health)
    or compliance_posture (Article 26 status).
    """

    __tablename__ = "scheduled_reports"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    schedule: Mapped[str] = mapped_column(String(16), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    report_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="security_summary", server_default="security_summary"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_send_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "schedule IN ('weekly', 'monthly')",
            name="ck_scheduled_reports_schedule",
        ),
        CheckConstraint(
            "report_type IN ('security_summary', 'compliance_posture')",
            name="ck_scheduled_reports_type",
        ),
    )


# ── Community Rule Packs ──────────────────────────────────────────


class CommunityRulePack(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A published set of detection rules shareable across orgs."""

    __tablename__ = "community_rule_packs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    install_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    org: Mapped["Org"] = relationship()


class CommunityRuleSubscription(Base, UUIDPrimaryKeyMixin):
    """An org's subscription to a community rule pack."""

    __tablename__ = "community_rule_subscriptions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community_rule_packs.id", ondelete="CASCADE"),
        nullable=False,
    )
    installed_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("org_id", "pack_id", name="uq_community_sub_org_pack"),
    )

    pack: Mapped["CommunityRulePack"] = relationship()
