"""
HTTP+SSE MCP client for remote MCP servers.

Implements the MCP 2024-11-05 specification over Streamable HTTP transport.
Unlike the StdioMCPClient which spawns a subprocess, this client communicates
with a remote MCP server over HTTP POST requests with optional SSE streaming.

MCP Streamable HTTP transport spec:
  - Client sends JSON-RPC 2.0 requests via HTTP POST to the server endpoint
  - Server responds with either a single JSON response or an SSE stream
  - SSE events carry JSON-RPC responses and notifications

Lifecycle:
    client = HTTPMCPClient("remote-fs", "http://mcp-server:3000/mcp")
    await client.start()           # handshake
    tools = await client.list_tools()
    result = await client.call_tool("read_file", {"path": "/README.md"})
    await client.stop()            # close HTTP client

References:
    https://spec.modelcontextprotocol.io/specification/basic/transports/#streamable-http
"""

from __future__ import annotations

import json
import logging

import httpx

from .mcp_client import MCPTool

log = logging.getLogger(__name__)


class HTTPMCPClient:
    """
    MCP client using Streamable HTTP transport — communicates with a remote
    MCP server via HTTP POST requests.

    Shares the same public interface as StdioMCPClient:
      - start(), stop(), connected, tools
      - list_tools(), call_tool()
    """

    def __init__(
        self,
        name: str,
        url: str,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.env = env or {}
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self._session_id: str | None = None
        self._connected = False
        self.tools: list[MCPTool] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Open HTTP client and complete the MCP initialization handshake."""
        headers = {}
        # Pass env vars as custom headers if the server expects auth tokens
        if self.env.get("MCP_AUTH_TOKEN"):
            headers["Authorization"] = f"Bearer {self.env['MCP_AUTH_TOKEN']}"

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers=headers,
        )
        log.info("MCP HTTP client '%s' connecting to %s", self.name, self.url)
        await self._initialize()
        self._connected = True

    async def stop(self) -> None:
        """Close the HTTP client."""
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None
        log.info("MCP HTTP client '%s' disconnected", self.name)

    @property
    def connected(self) -> bool:
        return self._connected and self._client is not None

    # ── MCP Protocol ──────────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        """MCP initialize handshake over HTTP."""
        result = await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "nova-orchestrator", "version": "1.0"},
        })
        log.debug("MCP HTTP '%s' initialized: %s", self.name, result)
        # Send initialized notification
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> list[MCPTool]:
        """Fetch tool definitions from the remote server."""
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
            "MCP HTTP server '%s': discovered %d tool(s): %s",
            self.name,
            len(self.tools),
            [t.name for t in self.tools],
        )
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Invoke a tool and return its text output."""
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

    # ── HTTP JSON-RPC transport ───────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict) -> dict:
        """
        Send a JSON-RPC 2.0 request over HTTP POST.

        The server may respond with:
          - A direct JSON response (Content-Type: application/json)
          - An SSE stream (Content-Type: text/event-stream) with the response
            embedded as a data event
        """
        if not self._client:
            raise RuntimeError(f"MCP HTTP client '{self.name}' is not connected")

        self._request_id += 1
        req_id = self._request_id

        body = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = await self._client.post(self.url, json=body, headers=headers)
        resp.raise_for_status()

        # Track session ID from response headers (MCP spec)
        if "Mcp-Session-Id" in resp.headers:
            self._session_id = resp.headers["Mcp-Session-Id"]

        content_type = resp.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse_response(resp.text, req_id)
        else:
            data = resp.json()
            if "error" in data:
                err = data["error"]
                raise RuntimeError(
                    f"MCP RPC error {err.get('code', '?')}: {err.get('message', str(err))}"
                )
            return data.get("result", {})

    def _parse_sse_response(self, text: str, req_id: int) -> dict:
        """Parse an SSE response body to extract the JSON-RPC result."""
        for line in text.splitlines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            # Match our request ID
            if data.get("id") == req_id:
                if "error" in data:
                    err = data["error"]
                    raise RuntimeError(
                        f"MCP RPC error {err.get('code', '?')}: {err.get('message', str(err))}"
                    )
                return data.get("result", {})
        raise RuntimeError(
            f"MCP HTTP server '{self.name}' SSE response did not contain "
            f"a result for request {req_id}"
        )

    async def _notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC 2.0 notification (no id, no response expected)."""
        if not self._client:
            return
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = await self._client.post(self.url, json=body, headers=headers)
            # Notifications may return 200 or 202 — both are fine
            if resp.status_code >= 400:
                log.warning(
                    "MCP notification '%s' to '%s' returned HTTP %d",
                    method, self.name, resp.status_code,
                )
        except Exception as e:
            log.warning("MCP notification '%s' to '%s' failed: %s", method, self.name, e)
