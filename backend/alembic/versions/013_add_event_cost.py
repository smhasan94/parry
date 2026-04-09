"""add estimated_cost_usd to agent_events

Every ingested event now carries an estimated USD cost derived from
the model pricing registry. Enables cost dashboards and budget
enforcement without an external billing API call.

Revision ID: 013
Revises: 012
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_events",
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_events", "estimated_cost_usd")
