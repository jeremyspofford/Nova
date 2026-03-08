"""
Per-stage model resolver — reads pipeline.stage_model.{role} from platform_config.

Feature-gated by pipeline.stage_defaults_enabled. Returns None when disabled
or unconfigured, so the caller falls through to the next resolution layer.

Cache: 30-second TTL (same pattern as model_resolver.py).
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger(__name__)

_cache: dict[str, str | None] = {}
_cache_at: float = 0.0
_CACHE_TTL = 30.0


async def _load_stage_config() -> dict[str, str | None]:
    """Load all pipeline.stage_model.* keys from platform_config."""
    from app.db import get_pool

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM platform_config "
                "WHERE key LIKE 'pipeline.stage_model.%' OR key = 'pipeline.stage_defaults_enabled'"
            )
        result: dict[str, str | None] = {}
        for r in rows:
            raw = r["value"]
            # platform_config stores JSONB — parse it
            if raw is None:
                result[r["key"]] = None
            else:
                val = json.loads(raw) if isinstance(raw, str) else raw
                result[r["key"]] = val if isinstance(val, str) else None
        return result
    except Exception as e:
        log.warning("Failed to load stage model config: %s", e)
        return {}


async def resolve_stage_model(role: str) -> str | None:
    """
    Resolve the per-stage model for a pipeline role.

    Returns the configured model ID, or None if:
      - Feature is disabled (pipeline.stage_defaults_enabled != "true")
      - No model configured for this role
      - Any error occurs (fail-open)
    """
    global _cache, _cache_at

    now = time.monotonic()
    if not _cache or (now - _cache_at) >= _CACHE_TTL:
        _cache = await _load_stage_config()
        _cache_at = now

    # Feature gate
    if _cache.get("pipeline.stage_defaults_enabled") != "true":
        return None

    model = _cache.get(f"pipeline.stage_model.{role}")
    if model:
        log.debug("Stage model for %s: %s", role, model)
    return model
