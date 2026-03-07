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
        # Handle multimodal content (list of ContentBlocks) or plain string
        if isinstance(m.content, list):
            content: Any = [
                {
                    "type": b.type,
                    **({"text": b.text} if b.text is not None else {}),
                    **({"image_url": b.image_url} if b.image_url is not None else {}),
                }
                if hasattr(b, "type") else b
                for b in m.content
            ]
        else:
            content = m.content
        msg: dict = {"role": m.role, "content": content}
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
