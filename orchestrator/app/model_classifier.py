"""
Intelligent model routing — classify user messages and route to optimal models.

Two-step process:
  1. classify_message() — cheap/fast LLM classifies the message into a category
  2. resolve_model_for_category() — maps category to first available model

Designed to run in parallel with memory retrieval (asyncio.gather) so it adds
zero perceived latency. Any failure silently falls back to Phase 1 auto-resolve.
"""
from __future__ import annotations

import json
import logging
import time

from app.clients import get_llm_client
from app.db import get_pool

log = logging.getLogger(__name__)

VALID_CATEGORIES = {"general", "code", "reasoning", "creative", "quick"}

CLASSIFIER_SYSTEM_PROMPT = (
    "Classify the user's message into exactly one category.\n"
    "Reply with ONLY the category name, nothing else.\n"
    "Categories: general, code, reasoning, creative, quick"
)

# Ordered preference for the classifier model itself (cheap & fast).
CLASSIFIER_MODEL_PREFERENCE = [
    "qwen2.5:1.5b",                  # Ollama local, ~50-150ms
    "groq/llama-3.1-8b-instant",     # Groq free tier, ~150-200ms
    "cerebras/llama3.1-8b",          # Cerebras free tier, ~400-800ms
]

DEFAULT_ROUTING_MAP: dict[str, list[str] | None] = {
    "general": None,
    "code": ["claude-sonnet-4-6", "gpt-4o", "chatgpt/gpt-4o"],
    "reasoning": ["chatgpt/o3", "chatgpt/o4-mini", "claude-sonnet-4-6"],
    "creative": ["claude-sonnet-4-6", "gpt-4o"],
    "quick": ["groq/llama-3.3-70b-versatile", "cerebras/llama3.1-8b", "gemini/gemini-2.5-flash"],
}

# ── Cached model availability ────────────────────────────────────────────────

_available_models: set[str] = set()
_available_at: float = 0.0
_AVAILABLE_TTL = 60.0


async def _refresh_available_models() -> set[str]:
    """Fetch available models from llm-gateway /v1/models/discover (cached 60s)."""
    global _available_models, _available_at

    now = time.monotonic()
    if _available_models and (now - _available_at) < _AVAILABLE_TTL:
        return _available_models

    try:
        client = get_llm_client()
        resp = await client.get("/v1/models/discover")
        resp.raise_for_status()
        providers = resp.json()
        models: set[str] = set()
        for provider in providers:
            if provider.get("available"):
                for m in provider.get("models", []):
                    models.add(m["id"])
        _available_models = models
        _available_at = now
        return models
    except Exception as e:
        log.debug("Failed to refresh available models: %s", e)
        return _available_models


# ── Config loading (cached to avoid per-request DB round-trips) ──────────────

_config_cache: dict[str, tuple[float, object]] = {}
_CONFIG_TTL = 10.0  # seconds


async def _get_config(key: str, default: str) -> str:
    """Read a platform_config value, cached for 10s. Returns default on any failure."""
    now = time.monotonic()
    cached = _config_cache.get(key)
    if cached and (now - cached[0]) < _CONFIG_TTL:
        return cached[1]

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM platform_config WHERE key = $1", key
            )
        val = json.loads(row["value"]) if row and row["value"] else default
        _config_cache[key] = (now, val)
        return val
    except Exception:
        return default


async def _is_routing_enabled() -> bool:
    val = await _get_config("llm.intelligent_routing", "false")
    return val is True or val == "true"


async def _get_classifier_model() -> str:
    return await _get_config("llm.classifier_model", "auto")


async def _get_timeout_ms() -> int:
    val = await _get_config("llm.classifier_timeout_ms", "500")
    try:
        return int(val)
    except (ValueError, TypeError):
        return 500


async def _get_routing_map() -> dict[str, list[str] | None]:
    raw = await _get_config("llm.model_routing_map", "")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return DEFAULT_ROUTING_MAP


# ── Classification ───────────────────────────────────────────────────────────

async def classify_message(user_message: str) -> str | None:
    """Classify a user message into a category. Returns None on any failure."""
    import asyncio
    classifier_model, timeout_ms = await asyncio.gather(
        _get_classifier_model(), _get_timeout_ms()
    )
    timeout_s = timeout_ms / 1000.0

    if classifier_model != "auto":
        # Explicit classifier model
        models_to_try = [classifier_model]
    else:
        models_to_try = list(CLASSIFIER_MODEL_PREFERENCE)

    client = get_llm_client()
    payload = {
        "model": "",
        "messages": [
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message[:500]},  # Truncate long messages
        ],
        "temperature": 0,
        "max_tokens": 10,
    }

    for model in models_to_try:
        try:
            payload["model"] = model
            resp = await client.post("/complete", json=payload, timeout=timeout_s)
            resp.raise_for_status()
            data = resp.json()
            raw = (data.get("content") or "").strip().lower()
            # Extract first word in case model returns extra text
            category = raw.split()[0] if raw else ""
            if category in VALID_CATEGORIES:
                log.debug("Classifier (%s): '%s' → %s", model, user_message[:50], category)
                return category
            log.debug("Classifier (%s) returned invalid category: %r", model, raw)
        except Exception as e:
            log.debug("Classifier model %s failed: %s", model, e)
            continue

    return None


async def resolve_model_for_category(category: str) -> str | None:
    """Given a category, return the first available model from the routing map.
    Returns None if the category maps to null (use default) or no models are available."""
    routing_map = await _get_routing_map()
    preference_list = routing_map.get(category)

    if preference_list is None:
        return None  # Category maps to default auto-resolve

    available = await _refresh_available_models()
    if not available:
        return None

    for model_id in preference_list:
        if model_id in available:
            return model_id

    return None


async def classify_and_resolve(user_message: str) -> tuple[str | None, str | None]:
    """Classify a message and resolve to an optimal model.
    Returns (category, model_id) or (None, None) on any failure.
    Designed to be called via asyncio.gather alongside memory retrieval."""
    if not await _is_routing_enabled():
        return None, None

    start = time.monotonic()

    category = await classify_message(user_message)
    if not category:
        return None, None

    model_id = await resolve_model_for_category(category)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if model_id:
        log.info("Router: category=%s → model=%s (%dms)", category, model_id, elapsed_ms)
    else:
        log.debug("Router: category=%s → default auto-resolve (%dms)", category, elapsed_ms)

    return category, model_id
