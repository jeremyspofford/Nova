"""
Nova Tool Registry — aggregates all tool sets into a single interface.

The runner imports ALL_TOOLS and execute_tool from here; it never
imports from individual tool modules directly. Adding a new tool set:
  1. Create orchestrator/app/tools/<name>_tools.py
  2. Import its list and execute_tool here
  3. Add to ALL_TOOLS and the dispatch table below

MCP tools are dynamic — registered via the MCP server registry at runtime.
Use get_all_tools() when building a tool list for an LLM request to include
them; ALL_TOOLS only contains the static built-ins.
"""
from __future__ import annotations

from nova_contracts import ToolDefinition

from app.tools.platform_tools import PLATFORM_TOOLS
from app.tools.platform_tools import execute_tool as _exec_platform
from app.tools.code_tools import CODE_TOOLS
from app.tools.code_tools import execute_tool as _exec_code
from app.tools.git_tools import GIT_TOOLS
from app.tools.git_tools import execute_tool as _exec_git
from app.tools.web_tools import WEB_TOOLS
from app.tools.web_tools import execute_tool as _exec_web

# Static built-in tools — always available, no external dependencies.
# Passed to CompleteRequest.tools for standard agent turns.
ALL_TOOLS: list[ToolDefinition] = PLATFORM_TOOLS + CODE_TOOLS + GIT_TOOLS + WEB_TOOLS

# Fast name → module lookup built once at import time
_PLATFORM_NAMES = {t.name for t in PLATFORM_TOOLS}
_CODE_NAMES     = {t.name for t in CODE_TOOLS}
_GIT_NAMES      = {t.name for t in GIT_TOOLS}
_WEB_NAMES      = {t.name for t in WEB_TOOLS}


def get_all_tools() -> list[ToolDefinition]:
    """
    Return all available tools: built-ins + dynamically-registered MCP tools.

    Call this when building a tool list for an LLM request so MCP server tools
    are included. Do NOT call at module import time — MCP servers are loaded
    asynchronously after startup.
    """
    try:
        from app.pipeline.tools.registry import get_mcp_tool_definitions
        return ALL_TOOLS + get_mcp_tool_definitions()
    except Exception:
        # MCP registry unavailable (e.g., during tests) — fall back to built-ins
        return list(ALL_TOOLS)


async def execute_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call to the appropriate module."""
    # MCP tools are namespaced as mcp__{server}__{tool}
    if name.startswith("mcp__"):
        try:
            from app.pipeline.tools.registry import execute_mcp_tool
            return await execute_mcp_tool(name, arguments)
        except Exception as e:
            return f"MCP dispatch error: {e}"

    if name in _PLATFORM_NAMES:
        return await _exec_platform(name, arguments)
    if name in _CODE_NAMES:
        return await _exec_code(name, arguments)
    if name in _GIT_NAMES:
        return await _exec_git(name, arguments)
    if name in _WEB_NAMES:
        return await _exec_web(name, arguments)

    all_names = [t.name for t in ALL_TOOLS]
    return f"Unknown tool '{name}'. Available: {all_names}"
