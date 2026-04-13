from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.core.config import settings
from app.core.correlation_id import CorrelationIdMiddleware
from app.core.exceptions import ConflictError, NotFoundError, ParryError, PolicyViolationError
from app.core.logging import setup_logging
from app.core.metrics import registry as metrics_registry
from app.core.metrics_middleware import MetricsMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.request_size import RequestSizeLimitMiddleware
from app.core.sentry import init_sentry

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    settings.validate_for_production()
    settings.log_startup_warnings()
    init_sentry()
    # License verification is fatal in on-prem mode — the backend
    # must not come up with a tampered or missing license file.
    from app.core import on_prem

    on_prem.load_on_startup()
    log.info(
        "parry.startup",
        env=settings.app_env,
        on_prem=on_prem.is_on_prem(),
    )
    yield

    # ── Graceful shutdown: drain connections before exit ──
    from app.core.redis_pool import close_pools
    from app.db.session import engine

    log.info("parry.shutdown.draining")
    await close_pools()
    await engine.dispose()
    log.info("parry.shutdown.complete")


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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Parry-Secret",
        "X-Request-ID",
    ],
)

# Request size limit — reject oversized bodies early, before rate limiting
app.add_middleware(RequestSizeLimitMiddleware)

# Rate limiting (added after CORS so CORS headers are always present)
app.add_middleware(RateLimitMiddleware)

# Correlation ID — binds request_id into structlog context for every log line
app.add_middleware(CorrelationIdMiddleware)

# Metrics — added last so it wraps everything (innermost middleware seen by requests)
app.add_middleware(MetricsMiddleware)


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
async def policy_violation_handler(request: Request, exc: PolicyViolationError) -> JSONResponse:
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


@app.get("/docs/scalar", include_in_schema=False)
async def scalar_docs() -> HTMLResponse:
    """Serve the Scalar API reference UI against our /openapi.json.

    Zero-dependency — Scalar's standalone bundle loads from their CDN
    and renders the full reference client-side. Kept off the OpenAPI
    schema itself via ``include_in_schema=False`` so it doesn't clutter
    the generated spec.
    """
    html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Parry API Reference</title>
    <style>
      body { margin: 0; background: #0b1220; }
    </style>
  </head>
  <body>
    <script id="api-reference" data-url="/openapi.json"></script>
    <script>
      // Dark theme to match the dashboard / landing page.
      var cfg = { theme: "deepSpace", layout: "modern", hideDownloadButton: false };
      document.getElementById("api-reference").dataset.configuration = JSON.stringify(cfg);
    </script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check with dependency status for DB and Redis."""
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
        from app.core.redis_pool import sync_redis

        r = sync_redis()
        r.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "0.1.0",
        "checks": checks,
    }


# ── Prometheus metrics endpoint ─────────────────────────────────


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint. Unauthenticated — firewall at the network layer."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(
        content=generate_latest(metrics_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Register API routers ────────────────────────────────────────

from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")
