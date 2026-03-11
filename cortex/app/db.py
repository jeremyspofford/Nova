"""asyncpg connection pool for Cortex — same database as orchestrator."""
from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs."""
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool() -> None:
    """Create the connection pool with retry."""
    global _pool
    import asyncio
    for attempt in range(1, 11):
        try:
            _pool = await asyncpg.create_pool(settings.pg_dsn, min_size=2, max_size=5, init=_init_connection)
            log.info("DB pool ready")
            return
        except (asyncpg.CannotConnectNowError, OSError) as exc:
            if attempt == 10:
                raise
            log.warning("Postgres not ready (attempt %d/10): %s", attempt, exc)
            await asyncio.sleep(2)


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
