"""Capability Registry — discovers and tracks execution capabilities.

Capabilities are discovered (not declared) from registered drivers.
The registry provides capability lookup and matching services to the
rest of the system.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.schema.capability import CapabilityDescriptor
from myharness.core.exceptions import CapabilityNotFoundError

logger = structlog.get_logger(__name__)


class CapabilityRegistry:
    """Discovers and tracks available execution capabilities.

    Capabilities are discovered from registered drivers. Each capability
    maps to one or more concrete actions on a specific driver.

    The registry is the system's "what can I do?" answer — it tells the
    cognitive pipeline what execution options are available.
    """

    def __init__(self) -> None:
        """Initialize the capability registry."""
        self._drivers: dict[str, Any] = {}
        self._capabilities: dict[str, CapabilityDescriptor] = {}
        self._driver_capabilities: dict[str, list[str]] = {}
        logger.info("capability_registry_initialized")

    async def register_driver(self, driver: Any) -> None:
        """Register a driver and discover its capabilities.

        Args:
            driver: A driver instance implementing UnifiedDriverProtocol.
        """
        driver_name = getattr(driver, "driver_name", "unknown")
        self._drivers[driver_name] = driver

        # Discover capabilities from the driver
        caps = getattr(driver, "capabilities", [])
        cap_ids: list[str] = []
        for cap in caps:
            self._capabilities[cap.name] = cap
            cap_ids.append(cap.name)

        self._driver_capabilities[driver_name] = cap_ids

        logger.info(
            "driver_registered",
            driver_name=driver_name,
            capabilities_count=len(caps),
        )

    async def discover_capabilities(self) -> list[CapabilityDescriptor]:
        """Get all discovered capabilities across all drivers.

        Returns:
            A list of all registered capability descriptors.
        """
        return list(self._capabilities.values())

    async def get_driver_for_capability(self, capability: str) -> Any:
        """Get the driver that provides a specific capability.

        Args:
            capability: The capability name.

        Returns:
            The driver instance that provides this capability.

        Raises:
            CapabilityNotFoundError: If no driver provides the capability.
        """
        cap = self._capabilities.get(capability)
        if cap is None:
            raise CapabilityNotFoundError(
                f"No driver found for capability: {capability}",
                code="CAPABILITY_NOT_FOUND",
                details={"capability": capability},
            )

        driver_name = cap.driver_name
        driver = self._drivers.get(driver_name)
        if driver is None:
            raise CapabilityNotFoundError(
                f"Driver '{driver_name}' for capability '{capability}' is not registered",
                code="DRIVER_NOT_FOUND",
                details={
                    "capability": capability,
                    "driver_name": driver_name,
                },
            )

        return driver

    async def list_available_capabilities(self) -> list[str]:
        """List all available capability names.

        Returns:
            A sorted list of capability name strings.
        """
        return sorted(self._capabilities.keys())

    async def check_capability(self, capability: str) -> bool:
        """Check if a specific capability is available.

        Args:
            capability: The capability name to check.

        Returns:
            True if the capability is registered and its driver is connected.
        """
        cap = self._capabilities.get(capability)
        if cap is None:
            return False

        driver = self._drivers.get(cap.driver_name)
        if driver is None:
            return False

        # Check if driver is healthy
        if hasattr(driver, "health_check"):
            try:
                healthy = await driver.health_check()
                return healthy
            except Exception:
                return False

        return True
