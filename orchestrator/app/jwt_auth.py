"""JWT token creation, verification, and refresh token rotation."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.config import settings
from app.db import get_pool

log = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30


def _get_jwt_secret() -> str:
    """Return JWT secret, generating one if not configured."""
    if settings.jwt_secret:
        return settings.jwt_secret
    raise RuntimeError("JWT_SECRET not configured")


async def ensure_jwt_secret() -> None:
    """Auto-generate and persist JWT_SECRET if not set.
    Called at startup — writes to platform_config so it survives restarts.
    """
    if settings.jwt_secret:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT value #>> '{}' FROM platform_config WHERE key = 'auth.jwt_secret'"
        )
        if existing and existing.strip('"'):
            settings.jwt_secret = existing.strip('"')
            return

        generated = secrets.token_hex(32)
        await conn.execute(
            """
            INSERT INTO platform_config (key, value, description, is_secret)
            VALUES ('auth.jwt_secret', $1::jsonb, 'Auto-generated JWT signing secret', TRUE)
            ON CONFLICT (key) DO UPDATE SET value = $1::jsonb, updated_at = NOW()
            """,
            f'"{generated}"',
        )
        settings.jwt_secret = generated
        log.info("Generated and stored JWT_SECRET in platform_config")


def create_access_token(user_id: str, email: str, is_admin: bool) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Verify and decode access token. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


async def create_refresh_token(user_id: str) -> str:
    """Create a refresh token, store its hash in DB, return the raw token."""
    raw_token = f"nrt_{secrets.token_urlsafe(48)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    uid = UUID(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            uid, token_hash, expires_at,
        )
    return raw_token


async def rotate_refresh_token(old_token: str) -> tuple[str, str, dict] | None:
    """Invalidate old refresh token, issue new access + refresh tokens.
    Returns (access_token, new_refresh_token, user_dict) or None if invalid.
    """
    token_hash = hashlib.sha256(old_token.encode()).hexdigest()

    pool = get_pool()
    async with pool.acquire() as conn:
        # Find and delete the old token atomically
        row = await conn.fetchrow(
            """
            DELETE FROM refresh_tokens
            WHERE token_hash = $1 AND expires_at > NOW()
            RETURNING user_id
            """,
            token_hash,
        )
        if not row:
            return None

        user_id = row["user_id"]
        user = await conn.fetchrow(
            "SELECT id, email, display_name, avatar_url, is_admin, provider "
            "FROM users WHERE id = $1",
            user_id,
        )
        if not user:
            return None

    from app.users import _user_dict
    user_dict = _user_dict(user)

    access = create_access_token(str(user_id), user["email"], user["is_admin"])
    refresh = await create_refresh_token(str(user_id))
    return access, refresh, user_dict


async def revoke_refresh_token(token: str) -> bool:
    """Revoke a refresh token. Returns True if it existed."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM refresh_tokens WHERE token_hash = $1",
            token_hash,
        )
    return result == "DELETE 1"


async def cleanup_expired_tokens() -> int:
    """Remove expired refresh tokens. Call periodically."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM refresh_tokens WHERE expires_at < NOW()"
        )
    # result is like "DELETE 5"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
