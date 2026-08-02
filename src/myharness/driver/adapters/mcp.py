"""MCP (Model Context Protocol) driver — real client implementation.

Implements the UnifiedDriverProtocol over the official MCP Python SDK
(protocol 14.4 / docs/protocol/04-execution-driver.md):

- ``tools/list`` → capability discovery (CapabilityDescriptor)
- ``tools/call`` → ``execute()``
- ``resources`` → ``sense()``

Transport: stdio (local subprocess servers) or streamable HTTP (remote
servers, per the 2026-07 stateless HTTP spec). One driver instance binds
to one MCP server.

Security note: MCP tools are execution primitives — NOT skills. Skills are
semantic-level templates that bind driver + action allowlist (protocol
14.3); tool poisoning from malicious servers is handled by ExecutionGuard
authorization on the call path.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionProgress, ExecutionResult, DriverStatus

logger = structlog.get_logger(__name__)


def _describe_tool(tool: Any) -> str:
    """Best-effort one-line description of an MCP tool."""
    desc = getattr(tool, "description", "") or ""
    return str(desc).strip() or f"MCP tool {getattr(tool, 'name', '?')}"


class MCPDriver(UnifiedDriverProtocol):
    """MCP protocol driver — real client over the official MCP SDK.

    Args:
        server_command: Command (str or list) launching the MCP server as a
            stdio subprocess (e.g. ``"npx"``, ``["python", "-m", "srv"]``).
        server_args: Extra args for the stdio subprocess.
        server_url: Streamable HTTP endpoint for a remote MCP server.
            Mutually exclusive with ``server_command``.

    Without any server configured the driver exists but reports
    ``not_configured`` — it never silently pretends to execute.
    """

    def __init__(
        self,
        server_command: str | list[str] | None = None,
        server_args: list[str] | None = None,
        server_url: str | None = None,
    ) -> None:
        if server_command is not None and server_url is not None:
            raise ValueError("MCPDriver: server_command and server_url are mutually exclusive")

        self._command = server_command
        self._args = server_args or []
        self._url = server_url

        self._capabilities: list[CapabilityDescriptor] = []
        self._resources: list[str] = []
        self._session: Any = None
        self._transport_ctx: Any = None  # stdio_client / streamable_http_client context
        self._transport_streams: Any = None  # (read, write) from the context
        self._server_info: dict[str, Any] = {}
        self._connected = False

    # ── Identity ────────────────────────────────────────────────────────

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "mcp"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.2.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities discovered from the MCP server (tools/list)."""
        return self._capabilities

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Connect to the MCP server and discover capabilities.

        Raises:
            RuntimeError: If no server is configured, or if the connection
                or ``tools/list`` fails.
        """
        if not self._configured():
            raise RuntimeError(
                "MCPDriver: no server configured — pass server_command or server_url"
            )

        if self._url is not None:
            from mcp.client.streamable_http import streamable_http_client

            self._transport_ctx = streamable_http_client(url=self._url)
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            command, args = self._command, self._args
            if isinstance(command, str):
                command = [command]
            params = StdioServerParameters(
                command=command[0], args=list(args) if args else None
            )
            self._transport_ctx = stdio_client(params)

        try:
            self._transport_streams = await self._transport_ctx.__aenter__()
            read_stream, write_stream = self._transport_streams

            from mcp import ClientSession

            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

            init = getattr(self._session, "initialize_result", None) or {}
            self._server_info = {
                "name": getattr(init, "serverInfo", None) and getattr(
                    init.serverInfo, "name", "unknown"
                ),
                "protocol": getattr(init, "protocolVersion", ""),
            }

            tools_result = await self._session.list_tools()
            tools = list(getattr(tools_result, "tools", []) or [])
            self._capabilities = [self._tool_to_capability(t) for t in tools]

            res_result = await self._session.list_resources()
            self._resources = [
                r.uri for r in getattr(res_result, "resources", []) or []
            ]

            self._connected = True
            logger.info(
                "mcp_driver_connected",
                server=self._server_info.get("name"),
                tools=len(tools),
                resources=len(self._resources),
            )
        except Exception:
            await self._teardown_transport()
            self._connected = False
            raise

    async def shutdown(self) -> None:
        """Close the MCP session and transport."""
        await self._teardown_transport()
        self._connected = False
        self._capabilities = []
        logger.info("mcp_driver_shutdown")

    async def _teardown_transport(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                logger.warning("mcp_session_close_failed", exc_info=True)
            self._session = None
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.warning("mcp_transport_close_failed", exc_info=True)
            self._transport_ctx = None
        self._transport_streams = None

    def _configured(self) -> bool:
        return self._command is not None or self._url is not None

    # ── Execution ───────────────────────────────────────────────────────

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Call an MCP tool (``tools/call``). ``action`` is the tool name.

        The call is a single-step proxy: it does not encode any skill
        semantics. Skill-level validation (allowlists, boundaries) happens
        in the harness layer before this method is reached.
        """
        started = time.perf_counter()
        if not self._connected or self._session is None:
            return ExecutionResult(
                success=False,
                error="MCPDriver: not connected — call initialize() first",
                metadata={"driver_name": self.driver_name},
            )

        try:
            result = await self._session.call_tool(action, arguments=parameters or {})
        except Exception as exc:
            logger.warning("mcp_tool_call_failed", tool=action, error=str(exc))
            return ExecutionResult(
                success=False,
                error=f"MCP tool '{action}' failed: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
                metadata={"driver_name": self.driver_name, "tool": action},
            )

        # MCP SDK field name: is_error (2.0+); older releases used isError.
        is_error = bool(
            getattr(result, "is_error", None)
            if getattr(result, "is_error", None) is not None
            else getattr(result, "isError", False)
        )
        content = getattr(result, "content", []) or []
        text_parts = [
            c.text for c in content if getattr(c, "type", "") == "text" and c.text
        ]
        output: Any = "\n".join(text_parts) if text_parts else content

        return ExecutionResult(
            success=not is_error,
            output=output,
            error=f"MCP tool '{action}' reported an error" if is_error else None,
            duration_ms=(time.perf_counter() - started) * 1000,
            metadata={"driver_name": self.driver_name, "tool": action},
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Streaming execution — MCP tools are non-streaming today; yields
        a single final progress event wrapping the result."""
        result = await self.execute(action, parameters, context)
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="complete" if result.success else "failed",
            message=str(result.output) if result.success else (result.error or ""),
        )

    # ── Sensing ─────────────────────────────────────────────────────────

    async def sense(self, capability: str) -> dict[str, Any]:
        """Read an MCP resource by URI (or list resources when ``capability``
        is ``"list_resources"``)."""
        if not self._connected or self._session is None:
            return {"connected": False, "error": "not connected"}

        if capability == "list_resources":
            return {"resources": self._resources, "count": len(self._resources)}

        try:
            result = await self._session.read_resource(capability)
            content = getattr(result, "contents", []) or []
            return {"resource": capability, "contents": content}
        except Exception as exc:
            return {"resource": capability, "error": str(exc)}

    # ── Health ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Whether the MCP session is connected and responsive."""
        if not self._connected or self._session is None:
            return False
        try:
            await self._session.send_ping()
            return True
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any]:
        """Current driver status."""
        return DriverStatus(
            connected=self._connected,
            capabilities_count=len(self._capabilities),
            version=self.driver_version,
            metadata={
                **self._server_info,
                "configured": self._configured(),
                "server_command": self._command,
                "server_url": self._url,
                "resources": self._resources[:10],
            },
        ).model_dump()

    # ── Helpers ─────────────────────────────────────────────────────────

    def _tool_to_capability(self, tool: Any) -> CapabilityDescriptor:
        """Map an MCP tool to a MyHarness capability descriptor."""
        return CapabilityDescriptor(
            name=getattr(tool, "name", "unknown"),
            description=_describe_tool(tool),
            driver_name=self.driver_name,
            actions=[
                CapabilityAction(
                    name=getattr(tool, "name", "unknown"),
                    description="Call MCP tool",
                )
            ],
        )
