"""
Model resolver — resolves "auto" default to the best available model via llm-gateway.
Caches the result for 30 seconds to avoid repeated HTTP calls.
"""
from __future__ import annotations

import logging
import time

from app.clients import get_llm_client
from app.config import settings

log = logging.getLogger(__name__)

_cached_model: str | None = None
_cached_source: str | None = None
_cached_at: float = 0.0
_CACHE_TTL = 30.0


async def resolve_default_model() -> str:
    """Call llm-gateway /v1/models/resolve and return the resolved model ID.
    Falls back to settings.default_model on any error."""
    global _cached_model, _cached_source, _cached_at

    now = time.monotonic()
    if _cached_model and (now - _cached_at) < _CACHE_TTL:
        return _cached_model

    try:
        client = get_llm_client()
        resp = await client.get("/v1/models/resolve")
        resp.raise_for_status()
        data = resp.json()
        model = data.get("model", settings.default_model)
        source = data.get("source", "auto")
        _cached_model = model
        _cached_source = source
        _cached_at = now
        return model
    except Exception as e:
        log.warning("Failed to resolve default model: %s — falling back to %s", e, settings.default_model)
        return settings.default_model


async def is_auto_resolved() -> bool:
    """Return True if the current default model was auto-resolved (not explicitly configured).
    Used to decide whether intelligent routing should be allowed to override the model."""
    # Ensure cache is populated
    await resolve_default_model()
    return _cached_source == "auto"
