"""Records HTTP request metrics for Prometheus.

Captures the matched route template (e.g. /api/v1/agents/{agent_id}) rather than
the raw path so cardinality stays bounded.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import record_request


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip /metrics itself to avoid feedback loops on scrapes
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Exception will propagate after we record it
            status_code = 500
            duration = time.perf_counter() - start
            record_request(
                method=request.method,
                route=_get_route_template(request),
                status=status_code,
                duration_seconds=duration,
            )
            raise

        duration = time.perf_counter() - start
        record_request(
            method=request.method,
            route=_get_route_template(request),
            status=status_code,
            duration_seconds=duration,
        )
        return response


def _get_route_template(request: Request) -> str:
    """Return the matched FastAPI route template for low-cardinality labels.

    Falls back to the raw path if no route was matched (e.g., 404).
    """
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path  # type: ignore[no-any-return]
    return request.url.path
