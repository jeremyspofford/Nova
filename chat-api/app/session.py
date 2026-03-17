"""
Session management — maps session_id to agent_id.
Sessions persist across WebSocket reconnects via Redis.
"""
from __future__ import annotations

import logging
from uuid import uuid4

import redis.asyncio as aioredis
from nova_contracts import AgentConfig

from app.config import settings

log = logging.getLogger(__name__)

SESSION_KEY = "nova:chat:session:{session_id}"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close the module-level Redis connection. Call at shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_or_create_session(session_id: str | None) -> tuple[str, str]:
    """
    Returns (session_id, agent_id).
    If session_id is None or unknown, creates a new session with a new agent.
    """
    redis = get_redis()

    if session_id:
        agent_id = await redis.get(SESSION_KEY.format(session_id=session_id))
        if agent_id:
            await redis.expire(SESSION_KEY.format(session_id=session_id), SESSION_TTL)
            return session_id, agent_id

    # Create a new agent via Orchestrator
    import httpx
    new_session_id = session_id or str(uuid4())

    async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=30.0) as client:
        resp = await client.post("/api/v1/agents", json={
            "config": {
                "name": settings.default_agent_name,
                "system_prompt": (
                    "You are a helpful AI assistant with persistent memory across conversations. "
                    "You are thoughtful, accurate, and concise. You remember what users tell you and "
                    "reference past context when relevant."
                ),
                "model": settings.default_model,
            }
        })
        resp.raise_for_status()
        agent = resp.json()

    agent_id = agent["id"]
    await redis.set(
        SESSION_KEY.format(session_id=new_session_id),
        agent_id,
        ex=SESSION_TTL,
    )
    log.info("Created new session %s → agent %s", new_session_id, agent_id)
    return new_session_id, agent_id
