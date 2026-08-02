"""Minimal MCP stdio mock server (JSON-RPC over stdio) for driver tests.

Implements just enough of the MCP protocol for MCPDriver integration
tests: initialize handshake, tools/list, tools/call, resources/list.
Deliberately uses only the standard library so it runs on any Python.

Run: python tests/fixtures/mcp_mock_server.py
"""

import json
import sys

TOOLS = [
    {
        "name": "add",
        "description": "Add two integers",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "echo",
        "description": "Echo the given text",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def handle(msg: dict) -> dict | None:
    """Handle one JSON-RPC request; None means 'no reply needed' (notification)."""
    method = msg.get("method")

    if method == "initialize":
        return {
            "protocolVersion": msg.get("params", {}).get(
                "protocolVersion", "2025-06-18"
            ),
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "myharness-mock", "version": "1.0.0"},
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "resources/list":
        return {"resources": []}
    if method == "tools/call":
        name = msg.get("params", {}).get("name")
        args = msg.get("params", {}).get("arguments", {}) or {}
        if name == "add":
            return {
                "content": [
                    {"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}
                ],
                "isError": False,
            }
        if name == "echo":
            return {
                "content": [{"type": "text", "text": str(args.get("text", ""))}],
                "isError": False,
            }
        return {
            "content": [{"type": "text", "text": f"unknown tool: {name}"}],
            "isError": True,
        }
    return {
        "content": [{"type": "text", "text": f"unhandled method: {method}"}],
        "isError": True,
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = handle(msg)
        if result is None:
            continue
        response = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
