"""Middleware to reject oversized request bodies before they're fully read.

Prevents OOM from malicious or accidental multi-GB uploads. Returns 413
Payload Too Large with a JSON body matching our standard error format.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# 2 MB — generous enough for large event batches, small enough to prevent abuse.
MAX_BODY_BYTES = 2 * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            if int(content_length) > self.max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request body too large. Max {self.max_bytes} bytes.",
                        "code": "PAYLOAD_TOO_LARGE",
                    },
                )
        return await call_next(request)
