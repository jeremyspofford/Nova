"""
Core bridge logic — session mapping and orchestrator communication.
Shared by all platform adapters.
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

SESSION_KEY = "nova:bridge:{platform}:{platform_id}"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _auth_headers() -> dict[str, str]:
    headers = {}
    if settings.nova_api_key:
        headers["X-API-Key"] = settings.nova_api_key
    return headers


async def get_or_create_session(platform: str, platform_id: str) -> tuple[str, str]:
    """
    Returns (session_id, agent_id) for a platform-specific chat.
    Creates a new agent if no session exists.
    """
    r = get_redis()
    key = SESSION_KEY.format(platform=platform, platform_id=platform_id)

    raw = await r.get(key)
    if raw:
        data = json.loads(raw)
        await r.expire(key, SESSION_TTL)
        return data["session_id"], data["agent_id"]

    session_id = str(uuid4())
    async with httpx.AsyncClient(
        base_url=settings.orchestrator_url, timeout=30.0
    ) as client:
        resp = await client.post(
            "/api/v1/agents",
            json={
                "config": {
                    "name": settings.default_agent_name,
                    "system_prompt": (
                        "You are a helpful AI assistant with persistent memory across conversations. "
                        "You are thoughtful, accurate, and concise. You remember what users tell you and "
                        "reference past context when relevant."
                    ),
                    "model": settings.default_model,
                }
            },
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        agent = resp.json()

    agent_id = agent["id"]
    await r.set(
        key,
        json.dumps({"session_id": session_id, "agent_id": agent_id}),
        ex=SESSION_TTL,
    )
    log.info("New session: %s/%s -> session=%s agent=%s", platform, platform_id, session_id, agent_id)
    return session_id, agent_id


async def reset_session(platform: str, platform_id: str) -> None:
    """Delete the session mapping, forcing a new agent on next message."""
    r = get_redis()
    key = SESSION_KEY.format(platform=platform, platform_id=platform_id)
    await r.delete(key)
    log.info("Reset session: %s/%s", platform, platform_id)


async def send_message(session_id: str, agent_id: str, text: str) -> str:
    """
    Send a message to the orchestrator's streaming endpoint.
    Collects the full response and returns it as a string.
    """
    messages = [{"role": "user", "content": text}]

    try:
        async with httpx.AsyncClient(
            base_url=settings.orchestrator_url, timeout=120.0
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/tasks/stream",
                json={
                    "agent_id": agent_id,
                    "messages": messages,
                    "session_id": session_id,
                },
                headers=_auth_headers(),
            ) as resp:
                resp.raise_for_status()
                parts: list[str] = []
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        delta = line[6:]
                        # Skip JSON objects (status updates, metadata)
                        # — only keep plain text deltas
                        try:
                            parsed = json.loads(delta)
                            if isinstance(parsed, dict):
                                if "error" in parsed:
                                    return f"Error: {parsed['error']}"
                                continue  # status/meta — not user-facing
                        except (json.JSONDecodeError, TypeError):
                            pass
                        if delta:
                            parts.append(delta)
                return "".join(parts)

    except httpx.HTTPStatusError as e:
        log.error("Orchestrator HTTP error: %s", e.response.status_code)
        return f"Sorry, I encountered an error (HTTP {e.response.status_code}). Please try again."
    except Exception as e:
        log.error("Orchestrator error: %s", e)
        return "Sorry, I encountered an error. Please try again."
