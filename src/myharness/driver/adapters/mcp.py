"""MCP (Model Context Protocol) driver. Stub implementation for MVP.

Provides MCP-based execution for skills that interact with MCP servers.
In the MVP, this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="mcp_tool_call",
        description="Call tools on MCP servers",
        driver_name="mcp",
        actions=[
            CapabilityAction(name="call_tool", description="Call an MCP tool"),
            CapabilityAction(name="list_tools", description="List available MCP tools"),
            CapabilityAction(name="get_resource", description="Read an MCP resource"),
            CapabilityAction(name="list_resources", description="List MCP resources"),
        ],
    ),
]


class MCPDriver(UnifiedDriverProtocol):
    """MCP protocol driver. Stub implementation for MVP.

    In the full implementation, this would connect to MCP servers
    using the Model Context Protocol. For the MVP, it returns a stub
    ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the MCP driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "mcp_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "mcp"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the MCP driver (stub — no-op)."""
        logger.info("mcp_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an MCP action (stub).

        Args:
            action: The MCP action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "mcp_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"MCPDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an MCP action with streaming (stub).

        Args:
            action: The MCP action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"MCPDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense MCP state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the MCP driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the MCP driver (stub — no-op)."""
        logger.info("mcp_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the MCP driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
