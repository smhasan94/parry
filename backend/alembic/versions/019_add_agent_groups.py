"""add agent_groups table + agents.group_id

Organize agents into named groups with inherited permissions.
An agent belongs to at most one group.

Revision ID: 019
Revises: 018
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_groups",
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
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("org_id", "name", name="uq_agent_groups_org_name"),
    )
    op.create_index("idx_agent_groups_org", "agent_groups", ["org_id"])

    # Add group_id to agents
    op.add_column(
        "agents",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_agents_group",
        "agents",
        ["group_id"],
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_agents_group", table_name="agents")
    op.drop_column("agents", "group_id")
    op.drop_index("idx_agent_groups_org", table_name="agent_groups")
    op.drop_table("agent_groups")
