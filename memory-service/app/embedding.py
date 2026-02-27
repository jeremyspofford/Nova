"""
Embedding client — calls LLM Gateway for embeddings, caches in Redis (24h) and PostgreSQL.
Consumers never see vectors; they only pass text in and receive memories out.
"""
from __future__ import annotations

import hashlib
import json
import logging

import httpx
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    return _redis


def _cache_key(text_hash: str) -> str:
    return f"nova:embed:{text_hash}"


def _hash_text(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()


async def get_embedding(
    text: str,
    session: AsyncSession,
    model: str = settings.embedding_model,
) -> list[float]:
    """
    Get embedding for text. Cache hit order: Redis (1ms) → PostgreSQL → LLM Gateway.
    """
    text_hash = _hash_text(text, model)
    redis_key = _cache_key(text_hash)

    # L1: Redis cache
    redis = get_redis()
    cached = await redis.get(redis_key)
    if cached:
        return json.loads(cached)

    # L2: PostgreSQL embedding cache
    row = await session.execute(
        text("SELECT embedding FROM embedding_cache WHERE content_hash = :h"),
        {"h": text_hash},
    )
    db_row = row.fetchone()
    if db_row:
        embedding = _parse_pg_vector(str(db_row[0]))
        await redis.setex(redis_key, settings.redis_embedding_cache_ttl, json.dumps(embedding))
        return embedding

    # L3: LLM Gateway
    embedding = await _call_llm_gateway(text, model)

    # Write-through to both caches
    await redis.setex(redis_key, settings.redis_embedding_cache_ttl, json.dumps(embedding))
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
    await session.execute(
        text("""
            INSERT INTO embedding_cache (content_hash, embedding, model)
            VALUES (:h, :e::halfvec, :m)
            ON CONFLICT (content_hash) DO NOTHING
        """),
        {"h": text_hash, "e": embedding_str, "m": model},
    )

    return embedding


async def get_embeddings_batch(
    texts: list[str],
    session: AsyncSession,
    model: str = settings.embedding_model,
) -> list[list[float]]:
    """Batch embedding with cache population."""
    async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
        resp = await client.post("/embed", json={"model": model, "texts": texts})
        resp.raise_for_status()
        data = resp.json()
    return data["embeddings"]


async def _call_llm_gateway(text: str, model: str) -> list[float]:
    async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
        resp = await client.post("/embed", json={"model": model, "texts": [text]})
        resp.raise_for_status()
        data = resp.json()
    return data["embeddings"][0]


def _parse_pg_vector(vec_str: str) -> list[float]:
    """Parse PostgreSQL vector string '[0.1,0.2,...]' to Python list."""
    return [float(x) for x in vec_str.strip("[]").split(",")]
