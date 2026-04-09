"""add red team runs and results tables

Backs the red-team feature: each run is a sandbox replay of the
bundled attack corpus against an agent's merged detector config and
policy. Two tables — runs (one row per execution) and results (one
row per attack within a run). No FKs into the agent_events
hypertable: the red team has its own storage, never touches real
event data.

Revision ID: 011
Revises: 010
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "red_team_runs",
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
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total_attacks", sa.Integer(), nullable=True),
        sa.Column("detected_count", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("grade", sa.String(1), nullable=True),
        sa.Column("category_scores", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "mode IN ('sandbox', 'live')", name="ck_red_team_runs_mode"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_red_team_runs_status",
        ),
        sa.CheckConstraint(
            "grade IS NULL OR grade IN ('A','B','C','D','F')",
            name="ck_red_team_runs_grade",
        ),
    )
    op.create_index(
        "idx_red_team_runs_agent",
        "red_team_runs",
        ["agent_id", "started_at"],
    )
    op.create_index(
        "idx_red_team_runs_org",
        "red_team_runs",
        ["org_id", "started_at"],
    )

    op.create_table(
        "red_team_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("red_team_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attack_id", sa.String(128), nullable=False),
        sa.Column("attack_category", sa.String(64), nullable=False),
        sa.Column("attack_severity", sa.String(16), nullable=False),
        sa.Column("detected", sa.Boolean(), nullable=False),
        sa.Column(
            "detectors_fired",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("max_confidence", sa.Float(), nullable=True),
        sa.Column("response_preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_red_team_results_run", "red_team_results", ["run_id"])
    op.create_index(
        "idx_red_team_results_undetected",
        "red_team_results",
        ["run_id"],
        postgresql_where=sa.text("detected = false"),
    )


def downgrade() -> None:
    op.drop_index("idx_red_team_results_undetected", table_name="red_team_results")
    op.drop_index("idx_red_team_results_run", table_name="red_team_results")
    op.drop_table("red_team_results")
    op.drop_index("idx_red_team_runs_org", table_name="red_team_runs")
    op.drop_index("idx_red_team_runs_agent", table_name="red_team_runs")
    op.drop_table("red_team_runs")
