"""add response_scan_mode to orgs

Three-way posture for the SDK's /proxy/scan-response path:
- off    — default, no scanning (observe-only)
- redact — sensitive patterns replaced with placeholders in-line
- block  — response containing sensitive data is rejected entirely

Revision ID: 008
Revises: 007
Create Date: 2026-04-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Explicitly named enum so downgrade can drop the Postgres type cleanly
RESPONSE_SCAN_MODE_ENUM = sa.Enum("off", "redact", "block", name="response_scan_mode")


def upgrade() -> None:
    RESPONSE_SCAN_MODE_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "orgs",
        sa.Column(
            "response_scan_mode",
            RESPONSE_SCAN_MODE_ENUM,
            nullable=False,
            server_default="off",
        ),
    )


def downgrade() -> None:
    op.drop_column("orgs", "response_scan_mode")
    RESPONSE_SCAN_MODE_ENUM.drop(op.get_bind(), checkfirst=True)
