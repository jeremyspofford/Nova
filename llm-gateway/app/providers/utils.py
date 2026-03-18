"""
Shared provider utilities — DRY helpers used by multiple providers.
"""
from __future__ import annotations

import json as _json
from typing import Any


def serialize_messages(messages: list) -> list[dict[str, Any]]:
    """Convert nova_contracts Message objects to plain dicts for LLM APIs.

    Handles multimodal content blocks and passes through cache_control
    for Anthropic prompt caching.
    """
    out = []
    for m in messages:
        # Handle multimodal content (list of ContentBlocks or dicts) or plain string
        if isinstance(m.content, list):
            content: Any = []
            for b in m.content:
                if isinstance(b, dict):
                    # Already a dict (e.g., from _build_prompt with cache_control)
                    content.append(b)
                elif hasattr(b, "type"):
                    block: dict[str, Any] = {"type": b.type}
                    if b.text is not None:
                        block["text"] = b.text
                    if b.image_url is not None:
                        block["image_url"] = b.image_url
                    if hasattr(b, "cache_control") and b.cache_control:
                        block["cache_control"] = b.cache_control
                    content.append(block)
                else:
                    content.append(b)
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
