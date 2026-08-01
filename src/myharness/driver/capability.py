"""Capability discovery from registered drivers.

Discovers what each driver can do by inspecting its capabilities list
and provides matching services for the cognitive layer.
"""

from __future__ import annotations

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityDescriptor

logger = structlog.get_logger(__name__)


class CapabilityDiscovery:
    """Discovers capabilities from registered drivers.

    Capabilities are discovered (not declared) — each driver reports
    its capabilities, and this class aggregates and matches them for
    the cognitive layer.
    """

    def __init__(self) -> None:
        """Initialize the capability discovery service."""
        logger.info("capability_discovery_initialized")

    async def discover_from_driver(
        self, driver: UnifiedDriverProtocol
    ) -> list[CapabilityDescriptor]:
        """Discover capabilities from a single driver.

        Args:
            driver: The driver to inspect.

        Returns:
            A list of capability descriptors from the driver.
        """
        caps = driver.capabilities
        logger.debug(
            "capabilities_discovered",
            driver_name=driver.driver_name,
            count=len(caps),
        )
        return caps

    async def match_capability(
        self,
        required: str,
        available: list[CapabilityDescriptor],
    ) -> CapabilityDescriptor | None:
        """Find the best matching capability from available options.

        Matching is case-insensitive. Returns the first exact name match,
        or the first partial name match.

        Args:
            required: The required capability name.
            available: List of available capability descriptors.

        Returns:
            The matching capability descriptor, or None if no match.
        """
        required_lower = required.lower()

        # Exact match
        for cap in available:
            if cap.name.lower() == required_lower:
                return cap

        # Partial match
        for cap in available:
            if required_lower in cap.name.lower():
                return cap

        logger.debug(
            "no_capability_match",
            required=required,
            available=[c.name for c in available],
        )
        return None
