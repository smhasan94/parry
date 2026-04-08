"""add plan column to orgs

Subscription tier column backing the plan_service quota enforcement.
All existing orgs default to FREE — they keep their current behaviour
unless a Stripe webhook upgrades them.

Revision ID: 009
Revises: 008
Create Date: 2026-04-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLAN_ENUM = sa.Enum("free", "growth", "pro", "enterprise", name="plan")


def upgrade() -> None:
    PLAN_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "orgs",
        sa.Column(
            "plan",
            PLAN_ENUM,
            nullable=False,
            server_default="free",
        ),
    )


def downgrade() -> None:
    op.drop_column("orgs", "plan")
    PLAN_ENUM.drop(op.get_bind(), checkfirst=True)
