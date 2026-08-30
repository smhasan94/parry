"""record which transport an MCP server was reached over

Until now every registered server was necessarily stdio, so the column
did not need to exist. HTTP and SSE change that: an operator reviewing
a suspicious server needs to know whether it is a local subprocess or a
remote endpoint someone else controls, because the answers to "who can
change this" differ completely.

``stdio`` is the server default so existing rows describe themselves
correctly without a backfill — every row written before this migration
was in fact stdio.

The uniqueness key stays ``(org_id, server_uri)``. The scheme already
separates stdio from remote, and one URL reached over SSE versus
streamable-HTTP is the same logical server: transport is a last-seen
attribute, not part of its identity.

Revision ID: 024
Revises: 023
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "transport",
            sa.String(length=8),
            nullable=False,
            server_default="stdio",
        ),
    )
    op.create_check_constraint(
        "ck_mcp_servers_transport",
        "mcp_servers",
        "transport IN ('stdio', 'http', 'sse')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mcp_servers_transport", "mcp_servers", type_="check")
    op.drop_column("mcp_servers", "transport")
