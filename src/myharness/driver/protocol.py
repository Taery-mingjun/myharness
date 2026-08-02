"""Unified execution driver protocol and driver manager.

All execution drivers implement the UnifiedDriverProtocol, which provides
a consistent interface for the cognitive layer regardless of the underlying
execution target (robot, browser, API, database, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import structlog

from myharness.core.exceptions import DriverNotAvailableError
from myharness.schema.capability import CapabilityDescriptor
from myharness.schema.driver import ExecutionProgress, ExecutionResult

logger = structlog.get_logger(__name__)


class UnifiedDriverProtocol(ABC):
    """Unified execution driver protocol.

    All drivers implement this protocol, providing a consistent interface
    for the cognitive layer. Per P7 (Protocol over Implementation), the
    upper layers never know about specific driver implementations.

    Each driver has:
    - A name and version for identification.
    - A set of capabilities describing what it can do.
    - An execute() method for synchronous-style execution.
    - An execute_stream() method for streaming/progress execution.
    - A sense() method for reading state from the environment.
    - Health check and lifecycle methods.
    """

    @property
    @abstractmethod
    def driver_name(self) -> str:
        """Unique driver name (e.g., 'api', 'browser', 'robot')."""
        ...

    @property
    @abstractmethod
    def driver_version(self) -> str:
        """Driver version string (semver)."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the driver — connect, authenticate, configure."""
        ...

    @abstractmethod
    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an action on this driver.

        Args:
            action: The action name (e.g., 'move_joint', 'click', 'query').
            parameters: Action-specific parameters.
            context: Optional execution context (e.g., session data).

        Returns:
            An ExecutionResult with success/failure and output data.
        """
        ...

    @abstractmethod
    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an action with streaming progress updates.

        Args:
            action: The action name.
            parameters: Action-specific parameters.
            context: Optional execution context.

        Yields:
            ExecutionProgress updates during the action.
        """
        ...

    @abstractmethod
    async def sense(self, capability: str) -> dict[str, Any]:
        """Read/sense the current state for a capability.

        Args:
            capability: The capability to sense (e.g., 'position', 'screenshot').

        Returns:
            A dictionary with the sensed data.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the driver is healthy and responsive.

        Returns:
            True if the driver is healthy.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the driver, releasing resources."""
        ...

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the driver.

        Returns:
            A dictionary with driver status information.
        """
        ...


class DriverManager:
    """Manages all execution drivers.

    Handles driver registration, lookup, execution routing, and lifecycle.
    The cognitive layer uses this manager to find and use drivers without
    knowing about specific implementations.
    """

    def __init__(self) -> None:
        """Initialize the driver manager."""
        self._drivers: dict[str, UnifiedDriverProtocol] = {}
        logger.info("driver_manager_initialized")

    async def register(self, driver: UnifiedDriverProtocol) -> None:
        """Register a driver with the manager.

        Args:
            driver: The driver instance to register.
        """
        await driver.initialize()
        self._drivers[driver.driver_name] = driver
        logger.info(
            "driver_registered",
            driver_name=driver.driver_name,
            driver_version=driver.driver_version,
            capabilities_count=len(driver.capabilities),
        )

    async def get(self, driver_name: str) -> UnifiedDriverProtocol | None:
        """Get a registered driver by name.

        Args:
            driver_name: The driver name to look up.

        Returns:
            The driver instance, or None if not found.
        """
        return self._drivers.get(driver_name)

    async def execute(
        self,
        driver_name: str,
        action: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """Execute an action on a named driver.

        Args:
            driver_name: The driver to execute on.
            action: The action to perform.
            parameters: Action parameters.

        Returns:
            An ExecutionResult.

        Raises:
            DriverNotAvailableError: If the driver is not registered.
        """
        driver = self._drivers.get(driver_name)
        if driver is None:
            raise DriverNotAvailableError(
                f"Driver not registered: {driver_name}",
                code="DRIVER_NOT_AVAILABLE",
                details={
                    "driver_name": driver_name,
                    "available": list(self._drivers.keys()),
                },
            )

        return await driver.execute(action, parameters)

    async def list_drivers(self) -> list[str]:
        """List all registered driver names.

        Returns:
            A sorted list of driver names.
        """
        return sorted(self._drivers.keys())

    async def discover_capabilities(self) -> list[CapabilityDescriptor]:
        """Discover capabilities from all registered drivers.

        Returns:
            A list of all capability descriptors across all drivers.
        """
        all_caps: list[CapabilityDescriptor] = []
        for driver in self._drivers.values():
            all_caps.extend(driver.capabilities)
        return all_caps

    async def shutdown_all(self) -> None:
        """Shutdown all registered drivers gracefully."""
        for name, driver in list(self._drivers.items()):
            try:
                await driver.shutdown()
                logger.info("driver_shutdown", driver_name=name)
            except Exception as exc:
                logger.error(
                    "driver_shutdown_error",
                    driver_name=name,
                    error=str(exc),
                )
        self._drivers.clear()
        logger.info("all_drivers_shutdown")
