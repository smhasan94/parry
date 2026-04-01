import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ── Enums ────────────────────────────────────────────────────────


class Severity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(str, enum.Enum):
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
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
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


class AgentEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_events"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    session: Mapped["AgentSession | None"] = relationship(back_populates="events")
    detections: Mapped[list["Detection"]] = relationship(back_populates="event", lazy="selectin")


# ── Detection ────────────────────────────────────────────────────


class Detection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "detections"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_events.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    detector: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    event: Mapped["AgentEvent"] = relationship(back_populates="detections")
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
