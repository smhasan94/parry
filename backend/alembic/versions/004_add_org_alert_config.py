"""add alert_config to orgs

Stores per-org alert channel config (Slack webhook URL, min severity).

Revision ID: 004
Revises: 003
Create Date: 2026-04-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("alert_config", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "alert_config")
