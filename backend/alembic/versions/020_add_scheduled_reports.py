"""add scheduled_reports table

Recurring security report digests delivered via email on a
weekly or monthly schedule.

Revision ID: 020
Revises: 019
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schedule", sa.String(16), nullable=False),
        sa.Column(
            "recipients",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("report_type", sa.String(32), nullable=False, server_default="security_summary"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schedule IN ('weekly', 'monthly')",
            name="ck_scheduled_reports_schedule",
        ),
        sa.CheckConstraint(
            "report_type IN ('security_summary', 'compliance_posture')",
            name="ck_scheduled_reports_type",
        ),
    )
    op.create_index("idx_scheduled_reports_org", "scheduled_reports", ["org_id"])
    op.create_index(
        "idx_scheduled_reports_due",
        "scheduled_reports",
        ["next_send_at"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_scheduled_reports_due", table_name="scheduled_reports")
    op.drop_index("idx_scheduled_reports_org", table_name="scheduled_reports")
    op.drop_table("scheduled_reports")
