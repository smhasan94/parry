"""Populate an org's shadow-AI view from the demo Okta tenant.

Usage:
    cd backend
    uv run python scripts/seed_shadow_ai_demo.py                        # demo org
    uv run python scripts/seed_shadow_ai_demo.py --clerk-org-id org_abc  # your org

Runs the real discovery pipeline against a checked-in Okta payload — same
parser, matcher, dedup and reconciliation the live /discovery/sso/sync
route uses. Nothing is stubbed, so what the dashboard shows afterwards is
what a real tenant would produce.

Idempotent: grants dedup on re-run, so this can be run before every demo.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Org
from app.discovery.catalog_seed import seed_catalog
from app.discovery.okta import parse_okta_response
from app.discovery.sso_probe import SSOProbeProcessor
from app.services import discovery_service

log = structlog.get_logger()

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "okta_demo_tenant.json"
DEMO_CLERK_ORG_ID = "demo_org_local"


async def _resolve_org(db: AsyncSession, clerk_org_id: str) -> Org:
    org = (
        await db.execute(select(Org).where(Org.clerk_org_id == clerk_org_id))
    ).scalar_one_or_none()
    if org is None:
        org = Org(name="Demo Corp", clerk_org_id=clerk_org_id)
        db.add(org)
        await db.flush()
        print(f"created org {clerk_org_id} ({org.id})")
    else:
        print(f"using existing org {clerk_org_id} ({org.id})")
    return org


async def main(clerk_org_id: str) -> int:
    if not FIXTURE.exists():
        print(f"fixture not found: {FIXTURE}", file=sys.stderr)
        return 1

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            stats = await seed_catalog(db)
            print(f"catalog: {stats['total']} entries")

            org = await _resolve_org(db, clerk_org_id)
            events = parse_okta_response(json.loads(FIXTURE.read_text()))

            processor = await SSOProbeProcessor.create(db)
            result = await processor.process_events(db=db, org_id=org.id, events=events)
            await db.commit()

            print(
                f"grants: {result.processed} processed, {result.created} new, "
                f"{result.deduplicated} deduplicated, {result.matched} matched the catalog"
            )

            shadow = await discovery_service.list_shadow_systems(db, org_id=org.id)
            summary = await discovery_service.shadow_summary(db, org_id=org.id)

            print(f"\nShadow AI — {summary['total']} systems nothing is monitoring:")
            for s in shadow:
                seen = s.last_seen_at.date().isoformat() if s.last_seen_at else "never"
                print(f"  {s.risk_level:<14} {s.name:<26} {s.provider_name or '—':<28} {seen}")
            print(f"\nby risk tier: {summary['by_risk_level']}")
            print("\nDashboard: /shadow-ai")
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clerk-org-id",
        default=DEMO_CLERK_ORG_ID,
        help="populate an existing org instead of the local demo org",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.clerk_org_id)))
