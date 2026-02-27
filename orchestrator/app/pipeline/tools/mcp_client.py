"""
Minimal stdio MCP (Model Context Protocol) client.

Implements the MCP 2024-11-05 specification for tool discovery and invocation
over a stdio subprocess transport using JSON-RPC 2.0 framing.

Lifecycle:
    client = StdioMCPClient("filesystem", "npx", ["-y", "@mcp/server-filesystem", "/workspace"])
    await client.start()           # spawn process + handshake
    tools = await client.list_tools()  # discover available tools
    result = await client.call_tool("read_file", {"path": "/workspace/README.md"})
    await client.stop()            # terminate process

References:
    https://spec.modelcontextprotocol.io/specification/basic/transports/#stdio
    https://www.jsonrpc.org/specification
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """A single tool exposed by an MCP server."""
    name: str
    description: str
    input_schema: dict
    server_name: str


class StdioMCPClient:
    """
    MCP client using stdio transport — spawns a subprocess and communicates
    via its stdin/stdout with JSON-RPC 2.0 framing.

    One client per MCP server. Tools are namespaced externally by the registry
    as mcp__{server_name}__{tool_name} to avoid collisions across servers.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self.name    = name
        self.command = command
        self.args    = list(args)
        self.env     = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self.tools: list[MCPTool] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the MCP server process and complete the initialization handshake."""
        merged_env = {**os.environ, **self.env}
        self._process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        log.info("MCP server '%s' spawned (pid=%d)", self.name, self._process.pid)
        await self._initialize()

    async def stop(self) -> None:
        """Terminate the MCP server process gracefully."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("MCP server '%s' did not exit in 5s — killing", self.name)
                self._process.kill()
        log.info("MCP server '%s' stopped", self.name)

    @property
    def connected(self) -> bool:
        """True if the subprocess is running."""
        return (
            self._process is not None
            and self._process.returncode is None
        )

    # ── MCP Protocol ──────────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        """
        MCP initialize handshake — must be the first request sent.
        After the response, we send an 'initialized' notification to complete
        the handshake (required by the spec before any other requests).
        """
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "nova-orchestrator", "version": "1.0"},
        })
        # Spec requires this notification after receiving the initialize response
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> list[MCPTool]:
        """
        Fetch tool definitions from the server and cache them in self.tools.
        Returns the MCPTool list (also accessible via self.tools afterwards).
        """
        resp = await self._rpc("tools/list", {})
        self.tools = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                server_name=self.name,
            )
            for t in resp.get("tools", [])
        ]
        log.info(
            "MCP server '%s': discovered %d tool(s): %s",
            self.name,
            len(self.tools),
            [t.name for t in self.tools],
        )
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Invoke a tool on the server and return its text output.

        MCP responses contain a 'content' array of typed items:
          {"type": "text", "text": "..."}
          {"type": "image", "mimeType": "image/png", "data": "..."}
          {"type": "resource", "uri": "..."}

        Text items are joined; other types produce a placeholder string.
        Raises RuntimeError if the server reports isError=True.
        """
        resp = await self._rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        content = resp.get("content", [])
        parts: list[str] = []
        for item in content:
            item_type = item.get("type", "")
            if item_type == "text":
                parts.append(item.get("text", ""))
            elif item_type == "image":
                parts.append(f"[image/{item.get('mimeType', 'unknown')}]")
            elif item_type == "resource":
                parts.append(f"[resource: {item.get('uri', '')}]")
            else:
                parts.append(str(item))

        if resp.get("isError"):
            raise RuntimeError(
                f"MCP tool '{tool_name}' on '{self.name}' returned error: "
                + " ".join(parts)
            )

        return "\n".join(parts) if parts else ""

    # ── JSON-RPC 2.0 transport ────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        """
        Send a JSON-RPC 2.0 request and wait for the matching response.

        Notifications and responses for other in-flight requests are skipped.
        Non-JSON lines (e.g. startup log messages) are also silently skipped.
        """
        if not self._process or self._process.returncode is not None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")

        self._request_id += 1
        req_id = self._request_id

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })
        self._process.stdin.write((msg + "\n").encode())
        await self._process.stdin.drain()

        # Read lines until we get the response for this specific request ID
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"MCP server '{self.name}' did not respond to '{method}' "
                    f"within {timeout}s"
                )

            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=remaining,
            )
            if not line:
                raise RuntimeError(
                    f"MCP server '{self.name}' closed stdout unexpectedly"
                )

            try:
                response = json.loads(line.decode().strip())
            except json.JSONDecodeError:
                # Skip non-JSON lines (startup messages, debug output, etc.)
                continue

            # Skip notifications (no "id" field)
            if "id" not in response:
                continue

            # Skip responses for different concurrent requests
            if response["id"] != req_id:
                continue

            if "error" in response:
                err = response["error"]
                raise RuntimeError(
                    f"MCP RPC error {err.get('code', '?')}: "
                    f"{err.get('message', str(err))}"
                )

            return response.get("result", {})

    async def _notify(self, method: str, params: dict) -> None:
        """
        Send a JSON-RPC 2.0 notification (no response expected, no id field).
        Used for 'notifications/initialized' after the initialize handshake.
        """
        if not self._process or self._process.returncode is not None:
            return
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self._process.stdin.write((msg + "\n").encode())
        await self._process.stdin.drain()
