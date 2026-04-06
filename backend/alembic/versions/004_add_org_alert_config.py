"""add alert_config to orgs

Stores per-org alert channel config (Slack webhook URL, min severity).

Revision ID: 004
Revises: 003
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("alert_config", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "alert_config")
