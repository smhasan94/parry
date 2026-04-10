"""add agent_permissions table

Per-agent (or org-wide default) tool permission boundaries with
deny-by-default support. Enforced at the proxy layer independently
of blocking_enabled.

Revision ID: 016
Revises: 015
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_permissions",
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
        sa.Column("mode", sa.String(16), nullable=False, server_default="disabled"),
        sa.Column("default_action", sa.String(8), nullable=False, server_default="allow"),
        sa.Column(
            "allowed_tools",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "blocked_tools",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "agent_id", name="uq_agent_permissions_org_agent"),
        sa.CheckConstraint(
            "mode IN ('enforcing', 'dry_run', 'disabled')",
            name="ck_agent_permissions_mode",
        ),
        sa.CheckConstraint(
            "default_action IN ('allow', 'deny')",
            name="ck_agent_permissions_default_action",
        ),
    )
    op.create_index("idx_agent_permissions_org", "agent_permissions", ["org_id"])
    op.create_index(
        "idx_agent_permissions_agent",
        "agent_permissions",
        ["agent_id"],
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_permissions_agent", table_name="agent_permissions")
    op.drop_index("idx_agent_permissions_org", table_name="agent_permissions")
    op.drop_table("agent_permissions")
