"""add mcp_servers table

Tracks every MCP (Model Context Protocol) server an org's agents
have connected to. Each row stores the canonical manifest + a sha256
hash for drift detection + a trust level that gates whether the
SDK's SentinelMCPClient will allow tool calls through.

Revision ID: 012
Revises: 011
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
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
        sa.Column("server_uri", sa.Text(), nullable=False),
        sa.Column("server_name", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "trust_level",
            sa.String(16),
            nullable=False,
            server_default="observed",
        ),
        sa.Column(
            "reputation",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
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
        sa.Column(
            "hash_history",
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "server_uri", name="uq_mcp_servers_org_uri"),
        sa.CheckConstraint(
            "trust_level IN ('observed', 'trusted', 'suspicious', 'blocked')",
            name="ck_mcp_servers_trust_level",
        ),
        sa.CheckConstraint(
            "reputation BETWEEN 0 AND 100",
            name="ck_mcp_servers_reputation",
        ),
    )
    op.create_index("idx_mcp_servers_org", "mcp_servers", ["org_id"])
    op.create_index(
        "idx_mcp_servers_trust", "mcp_servers", ["org_id", "trust_level"]
    )


def downgrade() -> None:
    op.drop_index("idx_mcp_servers_trust", table_name="mcp_servers")
    op.drop_index("idx_mcp_servers_org", table_name="mcp_servers")
    op.drop_table("mcp_servers")
