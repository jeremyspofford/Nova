"""
Tool permission helpers — reads/writes disabled tool groups from platform_config.

Default: everything enabled. Only stores what's OFF (disabled_groups list).
Key in platform_config: "tool_permissions" → {"disabled_groups": ["Web"]}

Permission resolution flow:
  platform_config (disabled_groups)
       │
       ▼
  get_disabled_tool_groups() → set[str]
       │
       ▼
  resolve_effective_tools(allowed_tools=None)
       ├─ filter registry by disabled groups
       ├─ filter MCP tools by disabled groups
       └─ optionally filter by pod allowed_tools
       │
       ▼
  list[ToolDefinition]  (passed to LLM)
"""
from __future__ import annotations

import json
import logging

from nova_contracts import ToolDefinition

from app.db import get_pool

log = logging.getLogger(__name__)

_CONFIG_KEY = "tool_permissions"


async def get_disabled_tool_groups() -> set[str]:
    """Return the set of disabled tool group names. Empty set = all enabled."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM platform_config WHERE key = $1", _CONFIG_KEY
        )
    if not row:
        return set()
    val = row["value"]
    if isinstance(val, str):
        val = json.loads(val)
    if isinstance(val, dict):
        return set(val.get("disabled_groups", []))
    return set()


async def resolve_effective_tools(
    allowed_tools: list[str] | None = None,
) -> tuple[list[ToolDefinition], set[str]]:
    """Centralized permission resolution — single entry point for all callers.

    Returns (effective_tools, disabled_groups) so callers can pass disabled_groups
    to the system prompt builder without a second DB query.

    Layers:
      1. Global permissions (disabled_groups from platform_config)
      2. Pod allowlist (optional — filters within permitted tools)
    """
    from app.tools import get_permitted_tools

    disabled = await get_disabled_tool_groups()
    tools = get_permitted_tools(disabled)

    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tools = [t for t in tools if t.name in allowed_set]

    return tools, disabled


def get_valid_group_names() -> set[str]:
    """Return all valid group names (built-in + MCP)."""
    from app.tools import get_registry

    names = {g.name for g in get_registry()}

    # Include MCP group names
    try:
        from app.pipeline.tools.registry import get_mcp_tool_definitions
        for t in get_mcp_tool_definitions():
            parts = t.name.split("__")
            if len(parts) >= 2:
                names.add(f"MCP: {parts[1]}")
    except Exception:
        pass

    return names


async def set_disabled_groups(groups: set[str]) -> None:
    """Replace the full set of disabled groups."""
    await _save_disabled_groups(groups)


async def get_tool_groups_with_status() -> list[dict]:
    """Return all groups with enabled/disabled status and tool names.

    Includes both static built-in groups and MCP server groups.
    """
    from app.tools import get_registry

    disabled = await get_disabled_tool_groups()
    groups: list[dict] = []

    # Static built-in groups
    for g in get_registry():
        groups.append({
            "name": g.name,
            "display_name": g.display_name,
            "description": g.description,
            "tools": [t.name for t in g.tools],
            "tool_count": len(g.tools),
            "enabled": g.name not in disabled,
            "is_mcp": False,
        })

    # MCP server groups
    try:
        from app.pipeline.tools.registry import get_mcp_tool_definitions
        mcp_tools = get_mcp_tool_definitions()
        # Group by server name
        servers: dict[str, list[str]] = {}
        for t in mcp_tools:
            parts = t.name.split("__")
            if len(parts) >= 2:
                server = parts[1]
                servers.setdefault(server, []).append(t.name)
        for server, tools in sorted(servers.items()):
            group_name = f"MCP: {server}"
            groups.append({
                "name": group_name,
                "display_name": f"MCP: {server}",
                "description": f"Tools from MCP server '{server}'",
                "tools": tools,
                "tool_count": len(tools),
                "enabled": group_name not in disabled,
                "is_mcp": True,
            })
    except Exception:
        pass

    return groups


async def _save_disabled_groups(groups: set[str]) -> None:
    """Persist disabled groups to platform_config."""
    pool = get_pool()
    value = json.dumps({"disabled_groups": sorted(groups)})
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO platform_config (key, value, description, updated_at)
            VALUES ($1, $2::jsonb, $3, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            _CONFIG_KEY,
            value,
            "Tool groups disabled by admin. Empty list = all enabled.",
        )
