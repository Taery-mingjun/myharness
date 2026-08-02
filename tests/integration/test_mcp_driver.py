"""MCPDriver integration tests against a real stdio MCP mock server.

Verifies protocol 14.4 mappings:
- tools/list → capability discovery
- tools/call → execute()
- health/shutdown lifecycle
- unconfigured driver never pretends to execute

Lifecycle note: MCP sessions (anyio cancel scopes) must be entered and
exited within the SAME asyncio task. pytest-asyncio runs each test in a
fresh task, so each test creates and closes its own driver inline —
a shared fixture would leak cancel-scope errors across tests.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from myharness.driver.adapters.mcp import MCPDriver

MOCK_SERVER = Path(__file__).parent.parent / "fixtures" / "mcp_mock_server.py"

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def connected_driver():
    """Create a connected MCPDriver; initialize and shut down in one task."""
    driver = MCPDriver(
        server_command=sys.executable, server_args=[str(MOCK_SERVER)]
    )
    await driver.initialize()
    try:
        yield driver
    finally:
        await driver.shutdown()


async def test_discovers_tools_as_capabilities():
    async with connected_driver() as driver:
        names = {c.name for c in driver.capabilities}
        assert "add" in names
        assert "echo" in names
        add_cap = next(c for c in driver.capabilities if c.name == "add")
        assert "Add two integers" in add_cap.description
        assert add_cap.driver_name == "mcp"


async def test_calls_tool_via_execute():
    async with connected_driver() as driver:
        result = await driver.execute("add", {"a": 2, "b": 3})
        assert result.success is True
        assert result.output == "5"

        result2 = await driver.execute("echo", {"text": "hello mcp"})
        assert result2.success is True
        assert result2.output == "hello mcp"


async def test_unknown_tool_reports_error():
    async with connected_driver() as driver:
        result = await driver.execute("nonexistent", {})
        assert result.success is False
        assert "reported an error" in (result.error or "")
        assert "unknown tool" in str(result.output)


async def test_health_check_when_connected():
    async with connected_driver() as driver:
        assert await driver.health_check() is True


async def test_sense_lists_resources():
    async with connected_driver() as driver:
        sensed = await driver.sense("list_resources")
        assert sensed.get("count") == 0


async def test_unconfigured_driver_fails_initialize():
    driver = MCPDriver()
    with pytest.raises(RuntimeError, match="no server configured"):
        await driver.initialize()
    assert await driver.health_check() is False


async def test_execute_before_initialize_returns_error():
    driver = MCPDriver(
        server_command=sys.executable, server_args=[str(MOCK_SERVER)]
    )
    result = await driver.execute("add", {"a": 1, "b": 1})
    assert result.success is False
    assert "not connected" in (result.error or "")


async def test_conflicting_transports_rejected():
    with pytest.raises(ValueError, match="mutually exclusive"):
        MCPDriver(server_command="npx", server_url="http://localhost:8000/mcp")


async def test_shutdown_disconnects():
    async with connected_driver() as driver:
        assert await driver.health_check() is True
        await driver.shutdown()
        assert await driver.health_check() is False
        assert driver.capabilities == []


async def test_stream_execution_wraps_result():
    async with connected_driver() as driver:
        events = []
        async for progress in driver.execute_stream("add", {"a": 1, "b": 2}):
            events.append(progress)
        assert len(events) == 1
        assert events[0].progress_pct == 100.0
        assert events[0].status == "complete"
        assert "3" in events[0].message
