"""Middleware that propagates or generates a correlation ID for every request.

If the caller sends X-Request-ID we reuse it; otherwise we mint a new UUID.
The ID is:
  1. Bound into structlog's contextvars so every log line includes it
  2. Returned as a response header so callers can correlate client-side
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

HEADER = "X-Request-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(HEADER) or str(uuid.uuid4())

        # Bind into structlog contextvars — all downstream log calls get it for free
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
