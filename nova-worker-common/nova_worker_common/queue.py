"""Redis queue helpers for Nova worker services."""
import json

import redis.asyncio as aioredis


async def create_redis_client(url: str) -> aioredis.Redis:
    """Create an async Redis client from a URL (e.g. ``redis://redis:6379/0``)."""
    return aioredis.from_url(url, decode_responses=True)


async def close_redis_client(client: aioredis.Redis) -> None:
    """Close an async Redis client."""
    await client.aclose()


async def push_to_engram_queue(
    redis_client: aioredis.Redis,
    raw_text: str,
    source_type: str,
    source_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """JSON-encode and LPUSH a payload to the engram ingestion queue."""
    payload: dict = {
        "raw_text": raw_text,
        "source_type": source_type,
    }
    if source_id is not None:
        payload["source_id"] = source_id
    if metadata is not None:
        payload["metadata"] = metadata
    await redis_client.lpush("engram:ingestion:queue", json.dumps(payload))


async def push_to_notification_queue(
    redis_client: aioredis.Redis,
    queue_name: str,
    data: dict,
) -> None:
    """JSON-encode and LPUSH arbitrary data to any Redis queue."""
    await redis_client.lpush(queue_name, json.dumps(data))
