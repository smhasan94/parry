"""add badge_public flag to agents

Opt-in boolean so agents can expose a public security score badge.
Defaults to false — badges are private until the org admin enables them.

Revision ID: 021
Revises: 020
Create Date: 2026-04-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("badge_public", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("agents", "badge_public")
