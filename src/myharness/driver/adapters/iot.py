"""IoT/MQTT driver. Stub implementation for MVP.

Provides IoT device interaction capabilities for skills that control
sensors, actuators, and smart devices via MQTT or other IoT protocols.
In the MVP, this is a stub.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionProgress, ExecutionResult

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="iot_device_control",
        description="Control IoT devices via MQTT or other protocols",
        driver_name="iot",
        actions=[
            CapabilityAction(name="publish", description="Publish to an MQTT topic"),
            CapabilityAction(name="subscribe", description="Subscribe to an MQTT topic"),
            CapabilityAction(name="set_device_state", description="Set a device state"),
            CapabilityAction(name="get_device_state", description="Get current device state"),
            CapabilityAction(name="discover_devices", description="Discover nearby IoT devices"),
        ],
    ),
]


class IoTDriver(UnifiedDriverProtocol):
    """IoT/MQTT driver. Stub implementation for MVP.

    In the full implementation, this would connect to MQTT brokers
    and IoT platforms using async MQTT clients (aiomqtt, etc.).
    For the MVP, it returns a stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the IoT driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "iot_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "iot"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the IoT driver (stub — no-op)."""
        logger.info("iot_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an IoT action (stub).

        Args:
            action: The IoT action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "iot_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"IoTDriver is a stub — action '{action}' not implemented",
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
        """Execute an IoT action with streaming (stub).

        Args:
            action: The IoT action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"IoTDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense IoT device state (stub).

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
        """Check if the IoT driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the IoT driver (stub — no-op)."""
        logger.info("iot_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the IoT driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
