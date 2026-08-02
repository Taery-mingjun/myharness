"""Global error handler middleware — catches unhandled exceptions in HTTP handlers."""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from myharness.core.exceptions import MyHarnessError

logger = structlog.get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global error handler for unhandled exceptions.

    Catches all unhandled exceptions from route handlers and converts
    them to structured JSON error responses. MyHarnessError subclasses
    include their error code and details in the response.

    Unexpected exceptions (not MyHarnessError) return a generic 500
    without leaking internal details.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except MyHarnessError as exc:
            logger.warning(
                "domain_error_in_http",
                error_type=type(exc).__name__,
                error_code=exc.code,
                error_message=exc.message,
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=self._http_status_for(exc),
                content={
                    "error": {
                        "type": type(exc).__name__,
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
            )
        except Exception as exc:
            logger.error(
                "unhandled_error_in_http",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=request.url.path,
                method=request.method,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "type": "InternalServerError",
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred.",
                    }
                },
            )

    @staticmethod
    def _http_status_for(exc: MyHarnessError) -> int:
        """Map MyHarnessError subclasses to HTTP status codes.

        Args:
            exc: The domain exception to map.

        Returns:
            An appropriate HTTP status code.
        """
        from myharness.core.exceptions import (
            CapabilityNotFoundError,
            DriverNotAvailableError,
            IdentityConflictError,
            MemoryNotFoundError,
            ProviderNotAvailableError,
            SkillLifecycleError,
            SkillNotFoundError,
            SkillValidationError,
        )

        # 404 — not found
        if isinstance(exc, (MemoryNotFoundError, SkillNotFoundError, CapabilityNotFoundError)):
            return 404

        # 503 — service unavailable
        if isinstance(exc, (DriverNotAvailableError, ProviderNotAvailableError)):
            return 503

        # 409 — conflict
        if isinstance(exc, IdentityConflictError):
            return 409

        # 422 — unprocessable entity (validation)
        if isinstance(exc, (SkillValidationError, SkillLifecycleError)):
            return 422

        # Default: 400 bad request
        return 400
