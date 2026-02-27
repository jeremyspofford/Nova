"""
FastAPI dependencies for API key authentication and Redis rate limiting.

Two separate auth paths:
  ApiKeyDep  — validates X-API-Key header; applied to all task + agent endpoints
  AdminDep   — validates X-Admin-Secret header; applied to key management endpoints

When REQUIRE_AUTH=false (local dev), ApiKeyDep returns a synthetic bypass key
so all handlers work identically without distributing real keys.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Any
from uuid import UUID  # still needed for type hints in AuthenticatedKey and touch_api_key

from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.db import lookup_api_key, touch_api_key
from app.store import get_redis

log = logging.getLogger(__name__)

class AuthenticatedKey:
    """Validated API key context injected into handlers via ApiKeyDep."""

    def __init__(self, row: dict[str, Any]):
        # id is None for the dev-bypass key to avoid FK violations in usage_events
        self.id: UUID | None = row["id"]
        self.name: str = row["name"]
        self.rate_limit_rpm: int = row["rate_limit_rpm"]


async def _apply_rate_limit(api_key_id: UUID, rate_limit_rpm: int) -> None:
    """Redis sliding-window rate limiter at 1-minute granularity.

    On the first request in a window the key is created with a 120s TTL,
    so it auto-expires without a cleanup job. Raises HTTP 429 if the
    counter exceeds rate_limit_rpm for the current minute.
    """
    window = int(time.time() / 60)
    rkey = f"nova:ratelimit:{api_key_id}:{window}"
    redis = get_redis()
    count = await redis.incr(rkey)
    if count == 1:
        await redis.expire(rkey, 120)  # auto-cleanup after 2 windows
    if count > rate_limit_rpm:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({rate_limit_rpm} rpm). Retry after the next minute.",
        )


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthenticatedKey:
    """Validate X-API-Key and enforce per-key rate limit.

    When REQUIRE_AUTH=false, returns a synthetic bypass key so local dev
    works without distributing keys. Usage events still write with the
    zero UUID so test traffic can be filtered from real traffic in reports.
    """
    if not settings.require_auth:
        return AuthenticatedKey({
            "id": None,   # None avoids FK violation in usage_events when no real key exists
            "name": "dev-bypass",
            "rate_limit_rpm": 9999,
        })

    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    row = await lookup_api_key(x_api_key)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    await _apply_rate_limit(row["id"], row["rate_limit_rpm"])

    # Fire-and-forget last_used_at update — zero latency impact on response
    asyncio.create_task(touch_api_key(row["id"]))

    return AuthenticatedKey(row)


async def require_admin(
    x_admin_secret: Annotated[str | None, Header(alias="X-Admin-Secret")] = None,
) -> None:
    """Validate X-Admin-Secret for key management endpoints.

    Intentionally separate from API key auth: a revoked API key cannot
    list or create other keys, and the admin secret is never distributed
    to API clients.
    """
    if not x_admin_secret or x_admin_secret != settings.nova_admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")


# Clean type aliases used in handler signatures
ApiKeyDep = Annotated[AuthenticatedKey, Depends(require_api_key)]
AdminDep = Annotated[None, Depends(require_admin)]
