"""add threat intelligence tables + org sharing toggle

Cross-org threat feed: threat_indicators (aggregated patterns),
threat_sightings (per-org junction), and org.threat_intel_sharing
boolean for opt-out.

Revision ID: 017
Revises: 016
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Org sharing toggle ──────────────────────────────────────
    op.add_column(
        "orgs",
        sa.Column(
            "threat_intel_sharing",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # ── Threat Indicators ───────────────────────────────────────
    op.create_table(
        "threat_indicators",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("pattern_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("detector_source", sa.String(100), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("confidence_avg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sighting_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("org_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("sample_reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "idx_threat_indicators_active",
        "threat_indicators",
        ["score"],
        postgresql_where=sa.text("promoted_at IS NOT NULL AND archived_at IS NULL"),
    )
    op.create_index(
        "idx_threat_indicators_category",
        "threat_indicators",
        ["category"],
    )

    # ── Threat Sightings ────────────────────────────────────────
    op.create_table(
        "threat_sightings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "indicator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("threat_indicators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "indicator_id", "org_id",
            name="uq_threat_sightings_indicator_org",
        ),
    )
    op.create_index(
        "idx_threat_sightings_indicator",
        "threat_sightings",
        ["indicator_id"],
    )
    op.create_index(
        "idx_threat_sightings_org",
        "threat_sightings",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_threat_sightings_org", table_name="threat_sightings")
    op.drop_index("idx_threat_sightings_indicator", table_name="threat_sightings")
    op.drop_table("threat_sightings")

    op.drop_index("idx_threat_indicators_category", table_name="threat_indicators")
    op.drop_index("idx_threat_indicators_active", table_name="threat_indicators")
    op.drop_table("threat_indicators")

    op.drop_column("orgs", "threat_intel_sharing")
