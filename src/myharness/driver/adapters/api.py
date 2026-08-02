"""REST API execution driver using httpx.

Provides HTTP-based execution for skills that interact with REST APIs.
Supports GET, POST, PUT, PATCH, DELETE methods with configurable base URL,
headers, and authentication.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionProgress, ExecutionResult

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="http_request",
        description="Make HTTP requests to REST APIs",
        driver_name="api",
        actions=[
            CapabilityAction(
                name="get",
                description="HTTP GET request",
                parameters={"url": "string", "params": "object"},
            ),
            CapabilityAction(
                name="post",
                description="HTTP POST request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="put",
                description="HTTP PUT request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="patch",
                description="HTTP PATCH request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="delete",
                description="HTTP DELETE request",
                parameters={"url": "string"},
            ),
        ],
    ),
]


class APIDriver(UnifiedDriverProtocol):
    """REST API execution driver using httpx.

    Provides HTTP-based execution for skills that interact with REST APIs.
    Uses httpx.AsyncClient for async HTTP calls with connection pooling,
    timeout handling, and retry support.
    """

    def __init__(
        self,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the API driver.

        Args:
            base_url: Base URL for all API requests.
            headers: Default headers for all requests.
            timeout: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._initialized = False

        self._capabilities = _DEFAULT_CAPABILITIES
        # Update driver name in capabilities
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "api_driver_created",
            base_url=base_url,
            driver_name=self.driver_name,
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "api"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the driver — create the HTTP client."""
        if self._initialized:
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url or None,
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout),
        )
        self._initialized = True
        logger.info("api_driver_initialized", base_url=self._base_url)

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an HTTP action.

        Supported actions: get, post, put, patch, delete.

        Args:
            action: The HTTP method or action name.
            parameters: Must include 'url' and optionally 'body'/'params'.
            context: Optional execution context.

        Returns:
            An ExecutionResult with the HTTP response.
        """
        if self._client is None:
            return ExecutionResult(
                success=False,
                error="Driver not initialized",
                metadata={"driver_name": self.driver_name},
            )

        start = time.monotonic()
        try:
            url = parameters.get("url", "")
            params = parameters.get("params")
            body = parameters.get("body")
            extra_headers = parameters.get("headers")

            method = action.lower()
            response: httpx.Response

            if method == "get":
                response = await self._client.get(
                    url, params=params, headers=extra_headers
                )
            elif method == "post":
                response = await self._client.post(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "put":
                response = await self._client.put(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "patch":
                response = await self._client.patch(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "delete":
                response = await self._client.delete(
                    url, params=params, headers=extra_headers
                )
            else:
                return ExecutionResult(
                    success=False,
                    error=f"Unsupported HTTP method: {action}",
                    metadata={"driver_name": self.driver_name},
                )

            duration_ms = (time.monotonic() - start) * 1000

            try:
                response_data = response.json()
            except ValueError:
                response_data = response.text

            success = 200 <= response.status_code < 300

            return ExecutionResult(
                success=success,
                output=response_data,
                error=(
                    f"HTTP {response.status_code}: {response.reason_phrase}"
                    if not success
                    else None
                ),
                duration_ms=duration_ms,
                metadata={
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "method": method,
                },
            )

        except httpx.TimeoutException as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ExecutionResult(
                success=False,
                error=f"Request timeout: {exc}",
                duration_ms=duration_ms,
                metadata={"driver_name": self.driver_name},
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "api_execution_error",
                action=action,
                error=str(exc),
            )
            return ExecutionResult(
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                metadata={"driver_name": self.driver_name},
            )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an HTTP action with streaming progress.

        For API calls, streaming is simulated — the entire request
        completes before yielding progress.

        Args:
            action: The HTTP method.
            parameters: Request parameters.
            context: Optional execution context.

        Yields:
            ExecutionProgress updates.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=0.0,
            status="running",
            message="Starting HTTP request...",
        )

        yield ExecutionProgress(
            action=action,
            progress_pct=50.0,
            status="running",
            message="Waiting for response...",
        )

        result = await self.execute(action, parameters, context)

        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message="Request complete" if result.success else f"Error: {result.error}",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense API state — perform a health check request.

        Args:
            capability: The capability to sense.

        Returns:
            A dictionary with the API status.
        """
        if capability == "health" or capability == "status":
            if self._client is None:
                return {"connected": False, "error": "Not initialized"}
            try:
                response = await self._client.get("/")
                return {
                    "connected": True,
                    "status_code": response.status_code,
                    "base_url": self._base_url,
                }
            except Exception as exc:
                return {"connected": False, "error": str(exc)}
        return {"capability": capability, "available": False}

    async def health_check(self) -> bool:
        """Check if the API driver is healthy.

        Returns:
            True if the client is initialized.
        """
        return self._initialized and self._client is not None

    async def shutdown(self) -> None:
        """Gracefully shutdown the driver, closing the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False
        logger.info("api_driver_shutdown")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the API driver.

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "initialized": self._initialized,
            "base_url": self._base_url,
            "capabilities_count": len(self._capabilities),
        }
