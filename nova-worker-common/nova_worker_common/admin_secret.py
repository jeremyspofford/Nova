"""Runtime admin-secret resolver for worker services.

The Nova admin secret is rotatable at runtime via the orchestrator's
`POST /api/v1/admin/rotate-secret` endpoint, which writes the new value to
`nova:config:auth.admin_secret` on Redis db 1. Workers that send the
`X-Admin-Secret` header on outbound HTTP calls must pick up the rotated value
without a restart, so they re-read Redis on a 30-second cache.

If Redis is unavailable or the key is unset, the env fallback (the value that
was baked into `settings.admin_secret` at startup) is returned. Operators can
always force a reset to the env value with:

    redis-cli -n 1 DEL nova:config:auth.admin_secret
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

_ADMIN_SECRET_CACHE_TTL = 30  # seconds


class AdminSecretResolver:
    """Per-service resolver with its own 30s cache and lazy Redis connection."""

    def __init__(self, redis_url: str, fallback: str):
        # Point the resolver at db 1 (shared nova:config:* namespace) regardless
        # of what db the worker's own redis_url targets.
        self._config_url = redis_url.rsplit("/", 1)[0] + "/1"
        self._fallback = fallback
        self._cache: dict[str, Any] = {"value": None, "ts": 0.0}
        self._redis: aioredis.Redis | None = None

    async def get(self) -> str:
        """Return the current admin secret (Redis-backed, env fallback, 30s cache)."""
        now = time.monotonic()
        if (
            now - self._cache["ts"] < _ADMIN_SECRET_CACHE_TTL
            and self._cache["value"] is not None
        ):
            return self._cache["value"]

        value: str | None = None
        try:
            if self._redis is None:
                self._redis = aioredis.from_url(self._config_url, decode_responses=True)
            raw = await self._redis.get("nova:config:auth.admin_secret")
            if raw:
                try:
                    parsed = json.loads(raw)
                    value = parsed if isinstance(parsed, str) and parsed else raw
                except (json.JSONDecodeError, TypeError):
                    value = raw
        except Exception:
            log.debug("Failed to read admin secret from Redis, using env fallback")

        if not value:
            value = self._fallback

        self._cache["value"] = value
        self._cache["ts"] = now
        return value

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            finally:
                self._redis = None
