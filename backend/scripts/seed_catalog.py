"""Load the AI vendor catalog into the database.

Usage:
    cd backend
    uv run python scripts/seed_catalog.py

Idempotent — safe to run on every deploy. Entries are keyed on
(vendor, service_name), so a refreshed catalog updates in place rather
than orphaning discovered systems that already reference those ids.
"""

import asyncio
import sys

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.discovery.catalog_seed import CatalogSeedError, seed_catalog

log = structlog.get_logger()


async def main() -> int:
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            stats = await seed_catalog(db)
            await db.commit()
    except CatalogSeedError as exc:
        print(f"catalog seed failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(
        f"catalog seeded: {stats['created']} created, "
        f"{stats['updated']} updated, {stats['total']} total"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
