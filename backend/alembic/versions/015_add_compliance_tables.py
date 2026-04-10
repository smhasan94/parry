"""add EU AI Act compliance tables

Four tables for Article 26 deployer obligations: ai_systems (register),
ai_system_suppliers (auto-populated from events), fria_documents
(versioned FRIA PDFs), serious_incidents (Art. 73 reporting).

Revision ID: 015
Revises: 014
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── AI System Register ──────────────────────────────────────
    op.create_table(
        "ai_systems",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("intended_purpose", sa.Text(), nullable=False),
        sa.Column("deployer_name", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("provider_contact", sa.Text(), nullable=True),
        sa.Column("deployment_date", sa.Date(), nullable=True),
        sa.Column("retired_date", sa.Date(), nullable=True),
        sa.Column("fria_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fria_status", sa.String(16), nullable=False, server_default="not_required"),
        sa.Column(
            "agent_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("annex_iii_category", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_ai_systems_risk_level",
        ),
        sa.CheckConstraint(
            "fria_status IN ('not_required', 'missing', 'draft', 'approved', 'stale')",
            name="ck_ai_systems_fria_status",
        ),
    )
    op.create_index("idx_ai_systems_org", "ai_systems", ["org_id"])
    op.create_index("idx_ai_systems_risk", "ai_systems", ["org_id", "risk_level"])

    # ── Supplier Register ───────────────────────────────────────
    op.create_table(
        "ai_system_suppliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier_name", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column(
            "first_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("event_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("provider_url", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "system_id", "supplier_name", "model_id",
            name="uq_ai_system_suppliers_system_supplier_model",
        ),
    )
    op.create_index("idx_suppliers_system", "ai_system_suppliers", ["system_id"])

    # ── FRIA Documents ──────────────────────────────────────────
    op.create_table(
        "fria_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("generated_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approver_title", sa.Text(), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.UniqueConstraint("system_id", "version", name="uq_fria_documents_system_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'archived')",
            name="ck_fria_documents_status",
        ),
    )
    op.create_index("idx_fria_org", "fria_documents", ["org_id"])
    op.create_index("idx_fria_system", "fria_documents", ["system_id"])

    # ── Serious Incidents ───────────────────────────────────────
    op.create_table(
        "serious_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id"),
            nullable=False,
        ),
        sa.Column(
            "system_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id"),
            nullable=True,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_to_authority_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authority_jurisdiction", sa.Text(), nullable=True),
        sa.Column("report_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("report_content", postgresql.JSONB(), nullable=False),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "incident_id", "report_version",
            name="uq_serious_incidents_incident_version",
        ),
    )
    op.create_index("idx_serious_incidents_org", "serious_incidents", ["org_id"])
    op.create_index(
        "idx_serious_incidents_overdue",
        "serious_incidents",
        ["deadline_at"],
        postgresql_where=sa.text("reported_to_authority_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_serious_incidents_overdue", table_name="serious_incidents")
    op.drop_index("idx_serious_incidents_org", table_name="serious_incidents")
    op.drop_table("serious_incidents")

    op.drop_index("idx_fria_system", table_name="fria_documents")
    op.drop_index("idx_fria_org", table_name="fria_documents")
    op.drop_table("fria_documents")

    op.drop_index("idx_suppliers_system", table_name="ai_system_suppliers")
    op.drop_table("ai_system_suppliers")

    op.drop_index("idx_ai_systems_risk", table_name="ai_systems")
    op.drop_index("idx_ai_systems_org", table_name="ai_systems")
    op.drop_table("ai_systems")
