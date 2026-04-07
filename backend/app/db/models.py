import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    severity: Mapped[Severity] = mapped_column(Enum(Severity), nullable=False)
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
    severity: Mapped[Severity] = mapped_column(Enum(Severity), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.OPEN, nullable=False
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
