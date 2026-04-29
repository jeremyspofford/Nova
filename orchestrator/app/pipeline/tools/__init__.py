"""
Pipeline tool integration — MCP server management and dynamic tool discovery.

This module manages connections to external MCP (Model Context Protocol) servers
and exposes their tools alongside Nova's built-in tools.

Usage in pipeline agents:
    from app.pipeline.tools import get_mcp_tool_definitions, execute_mcp_tool

Usage at startup (main.py lifespan):
    from app.pipeline.tools import load_mcp_servers, stop_all_servers
"""

from .registry import (
    disconnect_server,
    execute_mcp_tool,
    get_mcp_tool_definitions,
    list_connected_servers,
    load_mcp_servers,
    reload_mcp_server,
    stop_all_servers,
)

__all__ = [
    "load_mcp_servers",
    "stop_all_servers",
    "get_mcp_tool_definitions",
    "execute_mcp_tool",
    "list_connected_servers",
    "reload_mcp_server",
    "disconnect_server",
]
