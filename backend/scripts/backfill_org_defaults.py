"""Give existing orgs the starting configuration new ones now get.

Orgs created before onboarding provisioning have no org-default
permission boundary and no starter policy, so their dashboards show the
same empty state the defaults were added to fix.

Safe to run repeatedly: provisioning is idempotent and never overwrites
a decision someone already made, so an org that has configured its own
boundary or written a policy is left untouched.

Usage:
    cd backend
    uv run python scripts/backfill_org_defaults.py --dry-run
    uv run python scripts/backfill_org_defaults.py
"""

import argparse
import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Org
from app.services import onboarding_service

log = structlog.get_logger()


async def main(dry_run: bool) -> int:
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    provisioned = skipped = 0
    try:
        async with factory() as db:
            orgs = (await db.execute(select(Org).order_by(Org.created_at))).scalars().all()
            print(f"{len(orgs)} orgs")

            for org in orgs:
                result = await onboarding_service.provision_new_org(db, org)
                if result["provisioned"]:
                    provisioned += 1
                    print(f"  + {org.name} ({org.id}): {', '.join(result['created'])}")
                else:
                    skipped += 1

            if dry_run:
                await db.rollback()
                print(f"\ndry run — rolled back. would provision {provisioned}, skip {skipped}")
            else:
                await db.commit()
                print(f"\nprovisioned {provisioned}, already configured {skipped}")
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.dry_run)))
