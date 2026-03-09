"""Guest role isolation: model filtering, context stripping, tool blocking."""

import json
import logging
import time

from app.db import get_pool

logger = logging.getLogger(__name__)

GUEST_SYSTEM_PROMPT = """You are a helpful AI assistant.
You do not have access to any tools, files, or system information.
Do not speculate about the system you are running on, its configuration,
API keys, infrastructure, or internal details. If asked, say you don't
have that information."""

_cached_models: list[str] | None = None
_cache_time: float = 0


async def get_guest_allowed_models() -> list[str]:
    """Get list of model IDs guests are allowed to use. Cached for 60s."""
    global _cached_models, _cache_time
    now = time.time()
    if _cached_models is not None and now - _cache_time < 60:
        return _cached_models

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT value FROM platform_config WHERE key = 'guest_allowed_models'"
    )
    if row:
        try:
            val = row["value"]
            # platform_config value is JSONB — may come as list directly or as string
            if isinstance(val, list):
                _cached_models = val
            elif isinstance(val, str):
                _cached_models = json.loads(val)
            else:
                _cached_models = []
        except (json.JSONDecodeError, TypeError):
            _cached_models = []
    else:
        _cached_models = []
    _cache_time = now
    return _cached_models


async def validate_guest_model(model: str | None) -> str:
    """Validate and resolve model for guest user. Raises ValueError if not allowed."""
    allowed = await get_guest_allowed_models()
    if not allowed:
        raise ValueError("No models configured for guest access. Contact the administrator.")
    if model is None:
        return allowed[0]
    if model not in allowed:
        raise ValueError(f"Model '{model}' is not available for guest users.")
    return model
