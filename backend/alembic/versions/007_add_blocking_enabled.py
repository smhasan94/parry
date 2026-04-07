"""add blocking_enabled to orgs

Opt-in active blocking mode. When true, the SDK's synchronous
/api/v1/proxy/check path will reject HIGH/CRITICAL detections before
the LLM call fires. Default false so existing orgs keep observe-only
behavior until they explicitly switch over.

Revision ID: 007
Revises: 006
Create Date: 2026-04-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column(
            "blocking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("orgs", "blocking_enabled")
