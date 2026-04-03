"""
Database connection pool via asyncpg.

Manages the connection lifecycle and runs table creation on startup.
"""
from __future__ import annotations

import logging

import asyncpg

from app.config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS baseline_pgvector_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    embedding halfvec(768),
    source_type TEXT DEFAULT 'chat',
    source_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bpv_hnsw ON baseline_pgvector_items
    USING hnsw (embedding halfvec_cosine_ops) WITH (m=24, ef_construction=128);
"""


async def init_pool() -> asyncpg.Pool:
    """Create the connection pool and ensure the table exists."""
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    log.info("Database pool initialized, schema ensured")
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the current connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized — call init_pool() first")
    return _pool
