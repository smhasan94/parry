from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import sqlalchemy as sa
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ParryError, PolicyViolationError
from app.core.logging import setup_logging

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    settings.validate_for_production()
    settings.log_startup_warnings()
    log.info("parry.startup", env=settings.app_env)
    yield
    log.info("parry.shutdown")


app = FastAPI(
    title="Parry",
    description="AI Agent Runtime Security",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (added after CORS so CORS headers are always present)
from app.core.rate_limit import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware)


# ── Exception handlers ──────────────────────────────────────────


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(PolicyViolationError)
async def policy_violation_handler(
    request: Request, exc: PolicyViolationError
) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(ParryError)
async def parry_error_handler(request: Request, exc: ParryError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": exc.message, "code": exc.code},
    )


# ── Health check ─────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    """Health check with dependency status for DB and Redis."""
    import redis as redis_lib

    from app.db.session import engine

    checks: dict[str, str] = {}

    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    # Check Redis
    try:
        r = redis_lib.Redis.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        r.close()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "0.1.0",
        "checks": checks,
    }


# ── Register API routers ────────────────────────────────────────

from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")
