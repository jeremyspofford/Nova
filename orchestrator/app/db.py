"""
asyncpg connection pool, idempotent schema init, and query helpers
for API key management and usage event logging.

Design: raw asyncpg (no SQLAlchemy ORM). The orchestrator only needs
six queries — the ORM session lifecycle would add complexity with no gain.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app.config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """
    Register JSON/JSONB codecs on every new connection so asyncpg
    transparently serialises/deserialises Python dicts ↔ JSONB columns.

    Without this, asyncpg returns JSONB columns as raw strings — calling
    dict() on them raises "dictionary update sequence element has length 1".
    """
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db() -> None:
    """Create the connection pool and run idempotent schema migrations.
    Called from orchestrator lifespan on startup.
    """
    global _pool
    # asyncpg uses plain postgresql:// — strip the SQLAlchemy dialect prefix
    # so the same DATABASE_URL env var format works for both services.
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, init=_init_connection)
    await _run_schema_migrations()
    log.info("DB pool ready, schema applied")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — was init_db() called?")
    return _pool


async def _run_schema_migrations() -> None:
    """
    Versioned migration runner.

    Reads all *.sql files from app/migrations/ in lexicographic order and
    applies any that haven't been recorded in schema_migrations yet.
    Idempotent: safe to call on every startup.

    Migration files are named NNN_description.sql (e.g. 001_base_schema.sql).
    Each file is executed as a single transaction so a failure leaves the DB
    in a clean state — the failed migration can be fixed and re-run next start.
    """
    migrations_dir = Path(__file__).parent / "migrations"
    pool = get_pool()

    async with pool.acquire() as conn:
        # Bootstrap the migration tracking table on first run
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        applied: set[str] = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = sql_file.stem   # e.g. "001_base_schema"
            if version in applied:
                continue

            sql = sql_file.read_text()
            sql_stripped = re.sub(r"--[^\n]*", "", sql)

            async with conn.transaction():
                for statement in sql_stripped.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        await conn.execute(stmt)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )

            log.info(f"Applied migration: {version}")


# ── Key generation ────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, key_hash, key_prefix).

    raw_key    — shown once at creation, never stored in the DB
    key_hash   — SHA-256 hex digest stored for constant-time lookup
    key_prefix — first 12 chars for display (e.g. "sk-nova-xyzA")
    """
    raw = f"sk-nova-{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:12]
    return raw, key_hash, key_prefix


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ── API key queries ───────────────────────────────────────────────────────────

async def lookup_api_key(raw_key: str) -> dict[str, Any] | None:
    """Return the api_keys row for this raw key, or None if invalid/inactive."""
    key_hash = _hash_key(raw_key)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, is_active, rate_limit_rpm "
            "FROM api_keys WHERE key_hash = $1",
            key_hash,
        )
    if row is None or not row["is_active"]:
        return None
    return dict(row)


async def touch_api_key(api_key_id: UUID) -> None:
    """Update last_used_at. Always called via asyncio.create_task — never awaited directly."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
            api_key_id,
        )


def _row_to_dict(row) -> dict[str, Any]:
    """Convert asyncpg Record to dict, parsing JSONB string fields back to dicts."""
    d = dict(row)
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    return d


async def create_api_key_record(
    name: str,
    key_hash: str,
    key_prefix: str,
    rate_limit_rpm: int = 60,
    metadata: dict | None = None,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (name, key_hash, key_prefix, rate_limit_rpm, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id, name, key_prefix, is_active, rate_limit_rpm,
                      created_at, last_used_at, metadata
            """,
            name, key_hash, key_prefix, rate_limit_rpm,
            json.dumps(metadata or {}),
        )
    return _row_to_dict(row)


async def list_api_keys() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, key_prefix, is_active, rate_limit_rpm, "
            "       created_at, last_used_at, metadata "
            "FROM api_keys ORDER BY created_at DESC"
        )
    return [_row_to_dict(r) for r in rows]


async def revoke_api_key(key_id: UUID) -> bool:
    """Set is_active=False. Row is preserved for audit trail. Returns True if key existed."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET is_active = FALSE "
            "WHERE id = $1 AND is_active = TRUE",
            key_id,
        )
    return result == "UPDATE 1"


# ── Usage event insertion ─────────────────────────────────────────────────────

async def insert_usage_event(
    api_key_id: UUID | None,
    agent_id: UUID | None,
    session_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_ms: int | None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO usage_events
                (api_key_id, agent_id, session_id, model,
                 input_tokens, output_tokens, cost_usd, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            api_key_id,
            agent_id,
            session_id,
            model,
            input_tokens,
            output_tokens,
            float(cost_usd) if cost_usd is not None else None,
            duration_ms,
        )
