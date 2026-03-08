"""User CRUD operations — raw asyncpg queries."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.db import get_pool

log = logging.getLogger(__name__)


def _user_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    return d


async def create_user(
    email: str,
    password_hash: str | None = None,
    display_name: str | None = None,
    provider: str = "local",
    provider_id: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, display_name, provider, provider_id, is_admin)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, email, display_name, avatar_url, provider, provider_id, is_admin, created_at, updated_at
            """,
            email, password_hash, display_name, provider, provider_id, is_admin,
        )
    return _user_dict(row)


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, avatar_url, password_hash, provider, provider_id, is_admin, created_at, updated_at "
            "FROM users WHERE email = $1",
            email,
        )
    return _user_dict(row) if row else None


async def get_user_by_provider(provider: str, provider_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, avatar_url, password_hash, provider, provider_id, is_admin, created_at, updated_at "
            "FROM users WHERE provider = $1 AND provider_id = $2",
            provider, provider_id,
        )
    return _user_dict(row) if row else None


async def get_user_by_id(user_id: str | UUID) -> dict[str, Any] | None:
    pool = get_pool()
    uid = UUID(user_id) if isinstance(user_id, str) else user_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, avatar_url, password_hash, provider, provider_id, is_admin, created_at, updated_at "
            "FROM users WHERE id = $1",
            uid,
        )
    return _user_dict(row) if row else None


async def update_user(user_id: str | UUID, **fields) -> dict[str, Any] | None:
    allowed = {"display_name", "avatar_url"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return await get_user_by_id(user_id)

    uid = UUID(user_id) if isinstance(user_id, str) else user_id
    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    values = [uid] + list(updates.values())

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE users SET {set_clause}, updated_at = NOW() WHERE id = $1 "
            "RETURNING id, email, display_name, avatar_url, provider, provider_id, is_admin, created_at, updated_at",
            *values,
        )
    return _user_dict(row) if row else None


async def count_users() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")
