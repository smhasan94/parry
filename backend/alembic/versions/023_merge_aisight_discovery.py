"""merge aisight discovery layer into the AI system register

Folds aisight's shadow-AI discovery schema into parry's Article 26
register. One ``ai_systems`` row per AI system regardless of how it was
found — declared by a human, discovered by a probe, or observed via SDK
traffic. The ``origin`` discriminator tells them apart.

Ported from aisight: ai_catalog_entries, catalog_domains,
risk_classifications, probe_events, probe_credentials,
conformity_assessments. Dropped on the way in: ai_bom_records (columns
redistributed), organizations, users, aisight's audit_log.

Two column relaxations on ai_systems are load-bearing — a network probe
that sees traffic to api.openai.com cannot infer intended purpose or
risk tier, so both must tolerate absence:
  * intended_purpose  NOT NULL -> NULL
  * risk_level        gains an 'unclassified' member + default

Revision ID: 023
Revises: 022
Create Date: 2026-08-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Vendor catalog (global, NOT org-scoped) ─────────────────
    # Seeded from aisight's catalog/services.json. Shared across all
    # orgs: "what is Notion AI, which foundation models does it use,
    # does it train on customer data" is not tenant-specific.
    op.create_table(
        "ai_catalog_entries",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("vendor", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("foundation_models", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("oauth_app_ids", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("trains_on_user_data", sa.Boolean, nullable=True),
        sa.Column("data_retention_days", sa.Integer, nullable=True),
        sa.Column("has_enterprise_dpa", sa.Boolean, nullable=True),
        sa.Column("soc2_certified", sa.Boolean, nullable=True),
        sa.Column("default_risk_tier", sa.String(16), nullable=True),
        sa.Column("risk_tier_rationale", sa.Text, nullable=True),
        sa.Column("privacy_policy_url", sa.String(2048), nullable=True),
        sa.Column("tos_url", sa.String(2048), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vendor", "service_name", name="uq_catalog_vendor_service"),
        sa.CheckConstraint(
            "default_risk_tier IS NULL OR default_risk_tier IN "
            "('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_catalog_default_risk_tier",
        ),
    )

    op.create_table(
        "catalog_domains",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "catalog_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_catalog_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain", name="uq_catalog_domains_domain"),
    )
    # The network probe's hot path: resolve an observed domain -> vendor.
    op.create_index("idx_catalog_domains_domain", "catalog_domains", ["domain"])
    op.create_index("idx_catalog_domains_entry", "catalog_domains", ["catalog_entry_id"])

    # ── ai_systems: relax the register for discovered rows ──────
    # Postgres 11+ adds a NOT NULL column with a constant server_default
    # without rewriting the table, so no backfill statement is needed —
    # existing rows pick up 'declared' / 'active' automatically.
    op.add_column(
        "ai_systems",
        sa.Column("origin", sa.String(16), nullable=False, server_default="declared"),
    )
    op.add_column("ai_systems", sa.Column("discovery_source", sa.String(32), nullable=True))
    op.add_column(
        "ai_systems",
        sa.Column(
            "catalog_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_catalog_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("ai_systems", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_systems", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ai_systems",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column("ai_systems", sa.Column("deployment_context", sa.Text, nullable=True))

    # intended_purpose: probes cannot infer it.
    op.alter_column("ai_systems", "intended_purpose", existing_type=sa.Text(), nullable=True)

    # risk_level: widen the domain to admit unranked systems. Every
    # existing value is in the old 4-member set, which is a subset of
    # the new 5, so the constraint swap cannot fail on live data.
    op.drop_constraint("ck_ai_systems_risk_level", "ai_systems", type_="check")
    op.create_check_constraint(
        "ck_ai_systems_risk_level",
        "ai_systems",
        "risk_level IN ('unclassified', 'minimal', 'limited', 'high', 'unacceptable')",
    )
    op.alter_column(
        "ai_systems",
        "risk_level",
        existing_type=sa.String(16),
        server_default="unclassified",
    )

    op.create_check_constraint(
        "ck_ai_systems_origin",
        "ai_systems",
        "origin IN ('declared', 'discovered', 'instrumented')",
    )
    op.create_check_constraint(
        "ck_ai_systems_status",
        "ai_systems",
        "status IN ('active', 'inactive', 'blocked', 'retired')",
    )

    # A discovered system maps to at most one catalog vendor per org —
    # partial, because declared systems may legitimately share one
    # (two internal apps both built on Azure OpenAI).
    op.create_index(
        "uq_ai_systems_org_catalog_discovered",
        "ai_systems",
        ["org_id", "catalog_entry_id"],
        unique=True,
        postgresql_where=sa.text("origin = 'discovered' AND catalog_entry_id IS NOT NULL"),
    )
    # Drives the shadow-AI dashboard query.
    op.create_index("idx_ai_systems_org_origin", "ai_systems", ["org_id", "origin"])
    # NOTE: idx_ai_systems_org and idx_ai_systems_risk already exist (rev 015).

    # ── ai_system_suppliers: observed vs catalog-declared ───────
    # Absorbs ai_bom_records.foundation_model. Declared suppliers have
    # no usage timestamps until traffic confirms them, so the two
    # *_used_at columns drop their NOT NULL.
    op.add_column(
        "ai_system_suppliers",
        sa.Column("source", sa.String(16), nullable=False, server_default="observed"),
    )
    op.create_check_constraint(
        "ck_ai_system_suppliers_source",
        "ai_system_suppliers",
        "source IN ('observed', 'declared')",
    )
    op.alter_column(
        "ai_system_suppliers", "first_used_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.alter_column(
        "ai_system_suppliers", "last_used_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.drop_constraint(
        "uq_ai_system_suppliers_system_supplier_model", "ai_system_suppliers", type_="unique"
    )
    op.create_unique_constraint(
        "uq_ai_system_suppliers_system_supplier_model_source",
        "ai_system_suppliers",
        ["system_id", "supplier_name", "model_id", "source"],
    )

    # ── Risk classification history ─────────────────────────────
    # ai_systems.risk_level is the denormalized current tier; this table
    # is the audit trail behind it (LLM reasoning, confidence, evidence,
    # who approved). reviewed_by is Text, not FK users.id — parry has no
    # users table, Clerk owns identity (matches fria_documents.approved_by).
    op.create_table(
        "risk_classifications",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("risk_tier", sa.String(16), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("evidence_urls", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("reviewed_by", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source IN ('catalog', 'llm_draft', 'human_override')",
            name="ck_risk_classifications_source",
        ),
        sa.CheckConstraint(
            "risk_tier IN ('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_risk_classifications_tier",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')",
            name="ck_risk_classifications_status",
        ),
    )
    op.create_index("idx_risk_classifications_org", "risk_classifications", ["org_id"])
    op.create_index(
        "idx_risk_classifications_system", "risk_classifications", ["system_id", "created_at"]
    )

    # ── Probe events (raw discovery signal) ─────────────────────
    op.create_table(
        "probe_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("probe_type", sa.String(32), nullable=False),
        sa.Column("raw_payload", JSONB, nullable=False),
        sa.Column(
            "matched_catalog_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_catalog_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dedup_key", sa.String(255), nullable=False),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "dedup_key", name="uq_probe_events_org_dedup"),
        sa.CheckConstraint(
            "probe_type IN ('network', 'sso', 'browser')", name="ck_probe_events_type"
        ),
    )
    op.create_index("idx_probe_events_org", "probe_events", ["org_id"])
    op.create_index("idx_probe_events_system", "probe_events", ["system_id"])
    # Unprocessed-queue scan for the classification worker.
    op.create_index(
        "idx_probe_events_unprocessed",
        "probe_events",
        ["org_id", "created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # ── Probe credentials ───────────────────────────────────────
    # encrypted_secret is ciphertext at rest — the app encrypts before
    # insert. Never select this column into a response schema.
    op.create_table(
        "probe_credentials",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("probe_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("encrypted_secret", sa.String(2048), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(50), nullable=True),
        sa.Column("last_sync_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "probe_type IN ('network', 'sso', 'browser')", name="ck_probe_credentials_type"
        ),
    )
    op.create_index("idx_probe_credentials_org", "probe_credentials", ["org_id"])

    # ── Conformity assessments (Art. 43) ────────────────────────
    # Distinct obligation from fria_documents (Art. 27). Both survive.
    op.create_table(
        "conformity_assessments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_systems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("template_version", sa.String(50), nullable=True),
        sa.Column("evidence", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_review', 'compliant', 'non_compliant')",
            name="ck_conformity_assessments_status",
        ),
    )
    op.create_index("idx_conformity_org", "conformity_assessments", ["org_id"])
    op.create_index("idx_conformity_system", "conformity_assessments", ["system_id"])


def downgrade() -> None:
    op.drop_table("conformity_assessments")
    op.drop_table("probe_credentials")
    op.drop_table("probe_events")
    op.drop_table("risk_classifications")

    # ai_system_suppliers back to observed-only.
    op.drop_constraint(
        "uq_ai_system_suppliers_system_supplier_model_source",
        "ai_system_suppliers",
        type_="unique",
    )
    # Catalog-declared rows can collide once `source` leaves the key,
    # and would violate the restored NOT NULLs anyway. They carry no
    # observed data, so dropping them is lossless.
    op.execute("DELETE FROM ai_system_suppliers WHERE source = 'declared'")
    op.create_unique_constraint(
        "uq_ai_system_suppliers_system_supplier_model",
        "ai_system_suppliers",
        ["system_id", "supplier_name", "model_id"],
    )
    op.drop_constraint("ck_ai_system_suppliers_source", "ai_system_suppliers", type_="check")
    op.execute(
        "UPDATE ai_system_suppliers SET first_used_at = created_at "
        "WHERE first_used_at IS NULL"
    )
    op.execute(
        "UPDATE ai_system_suppliers SET last_used_at = COALESCE(first_used_at, created_at) "
        "WHERE last_used_at IS NULL"
    )
    op.alter_column(
        "ai_system_suppliers", "last_used_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.alter_column(
        "ai_system_suppliers", "first_used_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.drop_column("ai_system_suppliers", "source")

    # ── ai_systems ──────────────────────────────────────────────
    op.drop_index("idx_ai_systems_org_origin", table_name="ai_systems")
    op.drop_index("uq_ai_systems_org_catalog_discovered", table_name="ai_systems")
    op.drop_constraint("ck_ai_systems_status", "ai_systems", type_="check")
    op.drop_constraint("ck_ai_systems_origin", "ai_systems", type_="check")

    # LOSSY. Rows that only exist because a probe found them have no
    # place in a declaration-only register, and both restored NOT NULLs
    # would reject them. Discovery data is reproducible by re-running
    # probes; the register rows are not. Snapshot before downgrading.
    op.execute("DELETE FROM ai_systems WHERE origin IN ('discovered', 'instrumented')")
    op.execute(
        "UPDATE ai_systems SET intended_purpose = '(unspecified)' "
        "WHERE intended_purpose IS NULL"
    )
    op.execute("UPDATE ai_systems SET risk_level = 'minimal' WHERE risk_level = 'unclassified'")

    op.alter_column("ai_systems", "risk_level", existing_type=sa.String(16), server_default=None)
    op.drop_constraint("ck_ai_systems_risk_level", "ai_systems", type_="check")
    op.create_check_constraint(
        "ck_ai_systems_risk_level",
        "ai_systems",
        "risk_level IN ('minimal', 'limited', 'high', 'unacceptable')",
    )
    op.alter_column("ai_systems", "intended_purpose", existing_type=sa.Text(), nullable=False)

    op.drop_column("ai_systems", "deployment_context")
    op.drop_column("ai_systems", "status")
    op.drop_column("ai_systems", "last_seen_at")
    op.drop_column("ai_systems", "first_seen_at")
    op.drop_column("ai_systems", "catalog_entry_id")
    op.drop_column("ai_systems", "discovery_source")
    op.drop_column("ai_systems", "origin")

    op.drop_table("catalog_domains")
    op.drop_table("ai_catalog_entries")
