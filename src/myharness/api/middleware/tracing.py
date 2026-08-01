"""Tracing middleware — injects request IDs and correlation headers."""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"
_CORRELATION_ID_HEADER = "X-Correlation-ID"


class TracingMiddleware(BaseHTTPMiddleware):
    """Add request ID and correlation ID to every HTTP request/response.

    If the client provides an X-Request-ID header, it is reused.
    Otherwise, a new UUIDv4 is generated. Both the request ID and
    correlation ID are attached to the structlog context for the
    duration of the request.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate request ID
        request_id = request.headers.get(
            _REQUEST_ID_HEADER, str(uuid.uuid4())
        )
        correlation_id = request.headers.get(
            _CORRELATION_ID_HEADER, str(uuid.uuid4())
        )

        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
        )

        # Process the request
        response = await call_next(request)

        # Echo back the IDs in response headers
        response.headers[_REQUEST_ID_HEADER] = request_id
        response.headers[_CORRELATION_ID_HEADER] = correlation_id

        # Clean up context
        structlog.contextvars.unbind_contextvars("request_id", "correlation_id")

        return response
