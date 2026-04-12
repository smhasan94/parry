"""Public benchmark endpoint — no auth required.

Returns Parry's detection scores against a standardized attack corpus.
Used on the public leaderboard page.
"""

import structlog
from fastapi import APIRouter

from app.services.benchmark_service import CATEGORIES, run_benchmark

log = structlog.get_logger()

router = APIRouter()


@router.get("/results")
async def benchmark_results() -> dict:
    """Run the benchmark and return scored results.

    This is a pure computation — no DB, no external calls. The result
    is deterministic for a given engine version.
    """
    return run_benchmark()


@router.get("/categories")
async def benchmark_categories() -> list[str]:
    return CATEGORIES
