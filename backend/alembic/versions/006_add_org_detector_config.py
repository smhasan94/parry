"""add detector_config to orgs

Stores per-org detector tuning: trigger thresholds and enabled flags.

Revision ID: 006
Revises: 005
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("detector_config", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orgs", "detector_config")
