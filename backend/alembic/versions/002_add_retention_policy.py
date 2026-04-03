"""add TimescaleDB retention policy for agent_events

Revision ID: 002
Revises: 001
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Auto-drop agent_events chunks older than 90 days
    op.execute(
        "SELECT add_retention_policy('agent_events', INTERVAL '90 days', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('agent_events', if_exists => TRUE)")
