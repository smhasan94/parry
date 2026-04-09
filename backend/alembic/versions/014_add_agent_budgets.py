"""add agent_budgets table

Per-agent (or org-wide default) spend caps with configurable period
(hour/day/month) and alert thresholds. Enforced at proxy-check time
via Redis counters.

Revision ID: 014
Revises: 013
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_budgets",
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
            nullable=True,
        ),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("cap_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "alert_at_pcts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[75, 90, 100]'::jsonb"),
        ),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "agent_id", "period", name="uq_agent_budgets_org_agent_period"),
        sa.CheckConstraint("period IN ('hour', 'day', 'month')", name="ck_agent_budgets_period"),
        sa.CheckConstraint("cap_usd > 0", name="ck_agent_budgets_cap_positive"),
    )
    op.create_index(
        "idx_agent_budgets_agent",
        "agent_budgets",
        ["agent_id"],
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_budgets_agent", table_name="agent_budgets")
    op.drop_table("agent_budgets")
