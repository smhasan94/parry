"""add workos_organization_id to orgs

Optional WorkOS Organization ID. Set only when an enterprise customer
turns on SAML SSO; every other org stays on the default Clerk flow.
Nullable, no index — lookups happen per-login and are rare enough
that a seq scan on an orgs table is fine.

Revision ID: 010
Revises: 009
Create Date: 2026-04-08

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("workos_organization_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orgs", "workos_organization_id")
