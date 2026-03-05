"""
Shared provider utilities — DRY helpers used by multiple providers.
"""
from __future__ import annotations

import json as _json
from typing import Any


def serialize_messages(messages: list) -> list[dict[str, Any]]:
    """Convert nova_contracts Message objects to plain dicts for LLM APIs."""
    out = []
    for m in messages:
        msg: dict = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": _json.dumps(tc.arguments)}}
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.name:
            msg["name"] = m.name
        out.append(msg)
    return out
