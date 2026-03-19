"""
MCP Tool Registry — manages active server connections and provides a unified
tool interface that merges Nova's built-in tools with MCP server tools.

Workflow:
  startup  → load_mcp_servers()           Connect to all enabled DB entries
  request  → get_mcp_tool_definitions()   ToolDefinition list for LLM requests
  agent    → execute_mcp_tool(name, args) Dispatch tool call to the right server
  ops      → list_connected_servers()     Health / status check for the dashboard
  runtime  → reload_mcp_server(name)      Hot-reconnect without full restart
  shutdown → stop_all_servers()           Gracefully terminate all subprocesses

Tool naming convention (avoids collisions across servers):
  mcp__{server_name}__{tool_name}
  e.g. mcp__filesystem__read_file, mcp__brave-search__web_search
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nova_contracts import ToolDefinition

if TYPE_CHECKING:
    from .mcp_client import StdioMCPClient
    from .http_mcp_client import HTTPMCPClient

log = logging.getLogger(__name__)

# name → connected client (populated by load_mcp_servers at startup)
# Values are StdioMCPClient or HTTPMCPClient — both share the same public interface
_active_clients: dict[str, "StdioMCPClient | HTTPMCPClient"] = {}


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def load_mcp_servers() -> int:
    """
    Connect to all enabled stdio MCP servers from the database.
    Called once in the orchestrator lifespan. Returns the number connected.

    Errors for individual servers are logged and skipped — a bad config on one
    server should never prevent the orchestrator from starting.
    """
    from app.db import get_pool

    pool = get_pool()
    if pool is None:
        log.warning("DB not available — skipping MCP server load")
        return 0

    connected = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mcp_servers WHERE enabled = TRUE"
            )
        for row in rows:
            if await _connect_server(dict(row)):
                connected += 1
    except Exception as e:
        log.error("Failed to load MCP servers from DB: %s", e)

    return connected


async def stop_all_servers() -> None:
    """
    Gracefully stop all connected MCP server subprocesses.
    Called in the orchestrator lifespan shutdown.
    """
    for name, client in list(_active_clients.items()):
        try:
            await client.stop()
        except Exception as e:
            log.warning("Error stopping MCP server '%s': %s", name, e)
    _active_clients.clear()
    log.info("All MCP servers stopped")


# ── Server management ─────────────────────────────────────────────────────────

async def reload_mcp_server(name: str) -> bool:
    """
    Reconnect a specific MCP server from its current DB configuration.
    Used when the user edits a server config or manually triggers a reconnect.
    Returns True if successfully connected.
    """
    from app.db import get_pool

    pool = get_pool()
    if pool is None:
        return False

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mcp_servers WHERE name = $1", name
        )
    if not row:
        log.warning("MCP server '%s' not found in DB for reload", name)
        return False

    return await _connect_server(dict(row))


async def disconnect_server(name: str) -> None:
    """Disconnect and remove a specific MCP server from the active registry."""
    client = _active_clients.pop(name, None)
    if client:
        try:
            await client.stop()
        except Exception as e:
            log.warning("Error disconnecting MCP server '%s': %s", name, e)


async def _connect_server(cfg: dict) -> bool:
    """
    Connect to a single MCP server using its DB config dict.
    Dispatches to StdioMCPClient or HTTPMCPClient based on the transport field.
    Replaces any existing connection for the same server name.
    Returns True on success, False on failure.
    """
    name = cfg["name"]
    transport = cfg.get("transport", "stdio")

    # Cleanly disconnect any existing connection first
    if name in _active_clients:
        await disconnect_server(name)

    try:
        if transport == "http":
            from .http_mcp_client import HTTPMCPClient

            url = cfg.get("url")
            if not url:
                log.warning("MCP server '%s' has transport=http but no URL — skipping", name)
                return False

            client = HTTPMCPClient(
                name=name,
                url=url,
                env=dict(cfg.get("env") or {}),
            )
        else:
            from .mcp_client import StdioMCPClient

            if not cfg.get("command"):
                log.warning("MCP server '%s' has no command configured — skipping", name)
                return False

            client = StdioMCPClient(
                name=name,
                command=cfg["command"],
                args=list(cfg.get("args") or []),
                env=dict(cfg.get("env") or {}),
            )

        await client.start()
        await client.list_tools()
        _active_clients[name] = client
        log.info(
            "MCP server '%s' connected via %s (%d tools)",
            name, transport, len(client.tools),
        )
        return True
    except Exception as e:
        log.error("Failed to connect MCP server '%s' (%s): %s", name, transport, e)
        return False


# ── Tool discovery & dispatch ─────────────────────────────────────────────────

def get_mcp_tool_definitions() -> list[ToolDefinition]:
    """
    Build ToolDefinition objects for all tools from connected MCP servers.

    Tool names are namespaced: mcp__{server_name}__{tool_name}
    This ensures no collisions with Nova's built-in tools or across servers.
    Descriptions are prefixed with the server name for clarity in the LLM's
    tool list.
    """
    tools: list[ToolDefinition] = []
    for client in _active_clients.values():
        if not client.connected:
            continue
        for tool in client.tools:
            tools.append(ToolDefinition(
                name=f"mcp__{tool.server_name}__{tool.name}",
                description=f"[{tool.server_name}] {tool.description}",
                parameters=tool.input_schema,
            ))
    return tools


async def execute_mcp_tool(name: str, arguments: dict) -> str:
    """
    Execute an MCP tool by its fully-qualified namespaced name.

    Args:
        name: Tool name in the format 'mcp__{server_name}__{tool_name}'
        arguments: Arguments dict matching the tool's input schema

    Returns:
        The tool's text output, or an error message string.
    """
    parts = name.split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp":
        return (
            f"Invalid MCP tool name '{name}'. "
            "Expected format: mcp__server_name__tool_name"
        )

    _, server_name, tool_name = parts
    client = _active_clients.get(server_name)

    if client is None:
        return (
            f"MCP server '{server_name}' is not connected. "
            f"Connected servers: {list(_active_clients.keys())}"
        )

    try:
        return await client.call_tool(tool_name, arguments)
    except Exception as e:
        log.error(
            "MCP tool '%s' on server '%s' failed: %s",
            tool_name, server_name, e,
        )
        return f"MCP tool error: {e}"


# ── Tool catalog (for dashboard picker) ────────────────────────────────────────

def get_tools_by_server() -> list[dict]:
    """Tool details grouped by MCP server, for the dashboard tool picker."""
    result = []
    for name, client in _active_clients.items():
        if not client.connected:
            continue
        result.append({
            "category": name,
            "source": "mcp",
            "tools": [
                {"name": f"mcp__{name}__{t.name}", "description": t.description}
                for t in client.tools
            ],
        })
    return result


# ── Status / health ───────────────────────────────────────────────────────────

def list_connected_servers() -> list[dict]:
    """
    Return connection status for all active MCP server entries.
    Used by the dashboard to show live status alongside DB records.
    """
    return [
        {
            "name": name,
            "connected": client.connected,
            "tool_count": len(client.tools),
            "tools": [t.name for t in client.tools],
        }
        for name, client in _active_clients.items()
    ]
