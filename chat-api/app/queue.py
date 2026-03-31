"""
Redis-backed message queue for chat-api.

When the orchestrator is unreachable, messages are queued here and
drained FIFO when connectivity is restored.  Uses Redis db3 (chat-api's
existing allocation) via the shared connection in session.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.session import get_redis

log = logging.getLogger(__name__)

QUEUE_KEY = "nova:chat:pending-messages"


async def enqueue_message(session_id: str, agent_id: str, messages: list[dict]) -> int:
    """Push a message to the pending queue. Returns queue position (1-based)."""
    redis = get_redis()
    payload = json.dumps({
        "session_id": session_id,
        "agent_id": agent_id,
        "messages": messages,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    })
    length = await redis.rpush(QUEUE_KEY, payload)
    log.info("Enqueued message for session %s (position %d)", session_id, length)
    return length


async def dequeue_message() -> dict | None:
    """Pop the next message from the queue (FIFO). Returns None if empty."""
    redis = get_redis()
    raw = await redis.lpop(QUEUE_KEY)
    if raw is None:
        return None
    return json.loads(raw)


async def queue_length() -> int:
    """Return number of pending messages."""
    redis = get_redis()
    return await redis.llen(QUEUE_KEY)
