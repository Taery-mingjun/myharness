"""Driver adapters — concrete implementations of the UnifiedDriverProtocol.

Each adapter wraps a specific execution target (API, browser, database,
robot, MCP, computer, IoT) behind the unified protocol interface.

Provides a factory function for creating adapters by type.
"""

from __future__ import annotations

from myharness.driver.adapters.api import APIDriver
from myharness.driver.adapters.browser import BrowserDriver
from myharness.driver.adapters.computer import ComputerDriver
from myharness.driver.adapters.database import DatabaseDriver
from myharness.driver.adapters.iot import IoTDriver
from myharness.driver.adapters.mcp import MCPDriver
from myharness.driver.adapters.robot import RobotDriver
from myharness.driver.protocol import UnifiedDriverProtocol

__all__ = [
    "APIDriver",
    "BrowserDriver",
    "DatabaseDriver",
    "RobotDriver",
    "MCPDriver",
    "ComputerDriver",
    "IoTDriver",
    "create_adapter",
]


def create_adapter(driver_type: str, **kwargs) -> UnifiedDriverProtocol:
    """Factory function to create a driver adapter by type.

    Args:
        driver_type: The type of driver to create. One of:
            'api', 'browser', 'database', 'robot', 'mcp', 'computer', 'iot'.
        **kwargs: Additional keyword arguments passed to the adapter constructor.

    Returns:
        A UnifiedDriverProtocol instance.

    Raises:
        ValueError: If the driver type is unknown.
    """
    adapters: dict[str, type[UnifiedDriverProtocol]] = {
        "api": APIDriver,
        "browser": BrowserDriver,
        "database": DatabaseDriver,
        "robot": RobotDriver,
        "mcp": MCPDriver,
        "computer": ComputerDriver,
        "iot": IoTDriver,
    }

    adapter_cls = adapters.get(driver_type.lower())
    if adapter_cls is None:
        raise ValueError(
            f"Unknown driver type: '{driver_type}'. "
            f"Must be one of: {list(adapters.keys())}"
        )

    return adapter_cls(**kwargs)
