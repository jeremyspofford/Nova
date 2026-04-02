# llm-gateway/app/editor_tracker.py
"""
Track which editors are connected to the Nova LLM Gateway.

Stores per-editor connection state in Redis with 5-minute TTL.
Detection: primary via X-Nova-Editor header, fallback via User-Agent.
"""
from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

UA_PATTERNS: dict[str, str] = {
    "continue": "continue",
    "cline": "cline",
    "cursor": "cursor",
    "aider": "aider",
    "windsurf": "windsurf",
}

KNOWN_EDITORS = ["continue", "cline", "cursor", "aider", "windsurf", "generic"]
_KEY_PREFIX = "nova:editor:connection:"
_TTL = 300  # 5 minutes

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def detect_editor_slug(editor_hint: str | None, user_agent: str | None) -> str | None:
    """Identify the editor from an explicit hint header or User-Agent.

    Detection methods (in priority order):
    1. X-Nova-Editor header — set by the dashboard's test connection button
    2. User-Agent sniffing — works for Continue, Cline, Aider, and some others

    Returns an editor slug or None if unrecognized.
    """
    # Primary: explicit editor hint (from dashboard test or custom header)
    if editor_hint:
        hint_lower = editor_hint.lower().strip()
        if hint_lower in KNOWN_EDITORS:
            return hint_lower
        # Also accept "editor-continue" format
        if hint_lower.startswith("editor-"):
            slug = hint_lower.removeprefix("editor-")
            if slug in KNOWN_EDITORS:
                return slug

    # Fallback: User-Agent sniffing
    if user_agent:
        ua_lower = user_agent.lower()
        for slug, pattern in UA_PATTERNS.items():
            if pattern in ua_lower:
                return slug

    return None


async def record_connection(slug: str, user_agent: str | None) -> None:
    """Record that an editor just made a successful request."""
    try:
        r = await _get_redis()
        key = f"{_KEY_PREFIX}{slug}"

        # Read existing to increment counter
        raw = await r.get(key)
        count = 1
        if raw:
            try:
                prev = json.loads(raw)
                count = prev.get("request_count", 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        value = json.dumps({
            "last_seen": time.time(),
            "user_agent": user_agent or "",
            "request_count": count,
        })
        await r.set(key, value, ex=_TTL)
    except Exception as e:
        # Non-critical — don't break completions
        log.debug("Editor tracking write failed: %s", e)


async def get_connections() -> dict:
    """Return connection state for all known editors."""
    r = await _get_redis()
    now = time.time()
    connections: dict[str, dict] = {}

    for slug in KNOWN_EDITORS:
        key = f"{_KEY_PREFIX}{slug}"
        raw = await r.get(key)
        if raw:
            try:
                data = json.loads(raw)
                last_seen = data.get("last_seen", 0)
                age = now - last_seen
                if age < 60:
                    status = "connected"
                elif age < 300:
                    status = "idle"
                else:
                    status = "disconnected"
                connections[f"editor-{slug}"] = {
                    "editor": slug,
                    "last_seen": data.get("last_seen"),
                    "request_count": data.get("request_count", 0),
                    "status": status,
                }
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            connections[f"editor-{slug}"] = {
                "editor": slug,
                "last_seen": None,
                "request_count": 0,
                "status": "never",
            }

    return connections
