"""Adaptive tier-based model resolver.

Resolution chain:
1. Explicit model set -> use it directly (bypass tier system)
2. Explicit tier set -> resolve via preference lists
3. Neither -> infer tier from heuristics, then resolve

Budget ceiling applied for cortex-originated requests.
Effectiveness matrix consulted when sufficient data exists.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

from .config import settings
from .rate_limiter import check_remaining_quota
from .registry import MODEL_REGISTRY, MODEL_SPECS, _is_ollama_model

log = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------

TIER_ORDER = ["best", "mid", "cheap"]

TIER_CEILING: dict[tuple[str, str], str] = {
    # (requested_tier, budget_tier) -> effective_tier
    ("best", "best"): "best",
    ("best", "mid"): "mid",
    ("best", "cheap"): "cheap",
    ("mid", "best"): "mid",
    ("mid", "mid"): "mid",
    ("mid", "cheap"): "cheap",
    ("cheap", "best"): "cheap",
    ("cheap", "mid"): "cheap",
    ("cheap", "cheap"): "cheap",
}

QUALITY_THRESHOLDS = {"best": 0.80, "mid": 0.65, "cheap": 0.50}

EXPLORE_RATE = 0.05        # 5% of requests explore
EXPLORE_MIN_SAMPLES = 50   # models with fewer samples are "undersampled"

# -- In-memory caches ---------------------------------------------------------

_prefs_cache: dict[str, list[str]] | None = None
_prefs_cache_ts: float = 0.0
_budget_cache: str | None = None
_budget_cache_ts: float = 0.0
_effectiveness_cache: dict | None = None
_effectiveness_cache_ts: float = 0.0
_CACHE_TTL = 5.0  # seconds


# -- Public API ---------------------------------------------------------------

async def resolve_model(
    model: str | None,
    tier: str | None,
    task_type: str | None,
    request: Any,
    caller: str | None = None,
) -> str:
    """Full resolution chain -- returns a concrete model name.

    Args:
        model: Explicit model from request (bypasses tier system if set).
        tier: Explicit tier hint ("best"/"mid"/"cheap").
        task_type: Task type for effectiveness lookup.
        request: The CompleteRequest (for heuristic signals).
        caller: Value of X-Caller header (e.g. "cortex").

    Returns:
        Resolved model name string.

    Raises:
        ValueError: If no model can be resolved at any tier.
    """
    # Path 1: explicit model -- bypass entirely
    if model:
        return model

    # Path 2 or 3: resolve tier
    if not tier:
        tier = infer_tier(request)

    # Budget ceiling for cortex
    if caller == "cortex":
        tier = await _apply_budget_ceiling(tier)
        if tier == "none":
            raise BudgetExhaustedError()

    # Resolve tier -> model
    return await _resolve_tier_to_model(tier, task_type, request)


class BudgetExhaustedError(Exception):
    """Raised when cortex budget is exhausted."""
    pass


# -- Heuristic inference ------------------------------------------------------

def infer_tier(request: Any) -> str:
    """Infer tier from request signals. Fast, no I/O."""
    best_points = 0
    cheap_points = 0

    # Prompt length (rough token estimate: 4 chars ~ 1 token)
    total_chars = sum(
        len(m.content) if isinstance(m.content, str) else 100
        for m in (request.messages or [])
    )
    est_tokens = total_chars // 4
    if est_tokens < 500:
        cheap_points += 2
    elif est_tokens > 2000:
        best_points += 2

    # Max tokens
    if request.max_tokens:
        if request.max_tokens < 300:
            cheap_points += 2
        elif request.max_tokens > 2000:
            best_points += 2

    # Tool use
    if request.tools:
        best_points += 2

    # System prompt length
    for m in (request.messages or []):
        if getattr(m, "role", None) == "system":
            content = m.content if isinstance(m.content, str) else ""
            if len(content) < 200:
                cheap_points += 1
            elif len(content) > 1000:
                best_points += 1
            break

    # Temperature
    if request.temperature is not None:
        if request.temperature < 0.2:
            best_points += 1
        elif request.temperature > 0.8:
            cheap_points += 1

    # Code presence
    for m in (request.messages or []):
        content = m.content if isinstance(m.content, str) else ""
        if "```" in content:
            best_points += 2
            break

    score = best_points - cheap_points
    if score <= -2:
        return "cheap"
    if score <= 2:
        return "mid"
    return "best"


# -- Tier -> model resolution -------------------------------------------------

async def _resolve_tier_to_model(
    tier: str, task_type: str | None, request: Any,
) -> str:
    """Walk preference list for tier, filtered by availability + effectiveness."""
    prefs = await _get_tier_preferences()
    effectiveness = await _get_effectiveness_matrix()

    # Estimate request token count for context window check
    total_chars = sum(
        len(m.content) if isinstance(m.content, str) else 100
        for m in (request.messages or [])
    )
    est_request_tokens = total_chars // 4

    # Try requested tier, then fall back to lower tiers
    tier_idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    for try_tier in TIER_ORDER[tier_idx:]:
        candidates = prefs.get(try_tier, [])

        # Filter by effectiveness if we have data for this task_type
        if task_type and effectiveness:
            threshold = QUALITY_THRESHOLDS.get(try_tier, 0.5)
            candidates = _filter_by_effectiveness(
                candidates, task_type, effectiveness, threshold,
            )

        # Exploration: occasionally try undersampled models
        if task_type and effectiveness and random.random() < EXPLORE_RATE:
            undersampled = [
                m for m in candidates
                if _sample_count(m, task_type, effectiveness) < EXPLORE_MIN_SAMPLES
            ]
            if undersampled:
                chosen = random.choice(undersampled)
                resolved = _resolve_virtual(chosen)
                if resolved and resolved in MODEL_REGISTRY:
                    provider = MODEL_REGISTRY[resolved]
                    if provider.is_available:
                        has_quota, _ = await check_remaining_quota(resolved)
                        if has_quota:
                            log.info(
                                "Exploration: tier=%s task_type=%s → %s (undersampled)",
                                try_tier, task_type, resolved,
                            )
                            return resolved

        for model_id in candidates:
            # Resolve virtual identifiers
            resolved = _resolve_virtual(model_id)
            if resolved is None:
                continue

            # Check provider availability
            if resolved not in MODEL_REGISTRY:
                continue
            provider = MODEL_REGISTRY[resolved]
            if not provider.is_available:
                continue

            # Check rate limit quota (read-only)
            has_quota, _ = await check_remaining_quota(resolved)
            if not has_quota:
                continue

            # Check context window
            spec = MODEL_SPECS.get(resolved, {})
            ctx_window = spec.get("context_window", 128_000)
            if est_request_tokens > ctx_window * 0.9:  # 90% safety margin
                continue

            log.info(
                "Tier resolved: tier=%s task_type=%s -> model=%s",
                try_tier, task_type, resolved,
            )
            return resolved

    raise ValueError(
        f"No model available for tier={tier} task_type={task_type}. "
        "All providers exhausted or unavailable."
    )


def _resolve_virtual(model_id: str) -> str | None:
    """Resolve virtual model identifiers to real model names."""
    if model_id == "default-ollama":
        real = settings.default_ollama_model
        # Check if ollama is available via the registry
        if real in MODEL_REGISTRY:
            return real
        return None
    return model_id


def _sample_count(model_id: str, task_type: str, effectiveness: dict) -> int:
    """Get sample count for a model×task_type from effectiveness matrix."""
    key = f"{model_id}:{task_type}"
    entry = effectiveness.get(key)
    return entry.get("sample_count", 0) if entry else 0


def _filter_by_effectiveness(
    candidates: list[str],
    task_type: str,
    effectiveness: dict,
    threshold: float,
) -> list[str]:
    """Filter candidates by effectiveness score for this task_type.

    Only filters if we have sufficient data (n >= 10). Otherwise returns
    candidates unchanged.
    """
    filtered = []
    for model_id in candidates:
        key = f"{model_id}:{task_type}"
        entry = effectiveness.get(key)
        if entry and entry.get("sample_count", 0) >= 10:
            if entry.get("avg_score", 0) < threshold:
                continue  # Skip -- model underperforms for this task type
        filtered.append(model_id)

    # If filtering removed everything, return original list (fail open)
    return filtered if filtered else candidates


# -- Budget ceiling -----------------------------------------------------------

async def _apply_budget_ceiling(tier: str) -> str:
    """Cap the requested tier based on cortex budget state from Redis."""
    budget_tier = await _get_budget_tier()
    if budget_tier == "none":
        return "none"
    key = (tier, budget_tier)
    return TIER_CEILING.get(key, tier)


async def _get_budget_tier() -> str:
    """Read cortex budget tier from Redis (5s cache)."""
    global _budget_cache, _budget_cache_ts
    now = time.monotonic()
    if _budget_cache is not None and (now - _budget_cache_ts) < _CACHE_TTL:
        return _budget_cache

    try:
        from .registry import _get_redis_config
        value = await _get_redis_config("cortex.budget_tier", "best")
        _budget_cache = value
    except Exception:
        _budget_cache = "best"
    _budget_cache_ts = now
    return _budget_cache


# -- Tier preferences ---------------------------------------------------------

async def _get_tier_preferences() -> dict[str, list[str]]:
    """Read tier preference lists from Redis, fallback to config defaults."""
    global _prefs_cache, _prefs_cache_ts
    now = time.monotonic()
    if _prefs_cache is not None and (now - _prefs_cache_ts) < _CACHE_TTL:
        return _prefs_cache

    prefs = _default_preferences()
    try:
        from .registry import _get_redis_config
        raw = await _get_redis_config("llm.tier_preferences", "")
        if raw:
            override = json.loads(raw)
            for tier_name in TIER_ORDER:
                if tier_name in override:
                    prefs[tier_name] = override[tier_name]
    except Exception:
        pass  # use defaults

    _prefs_cache = prefs
    _prefs_cache_ts = now
    return prefs


def _default_preferences() -> dict[str, list[str]]:
    """Parse default preferences from config (comma-separated strings)."""
    return {
        "best": [m.strip() for m in settings.tier_preferences_best.split(",")],
        "mid": [m.strip() for m in settings.tier_preferences_mid.split(",")],
        "cheap": [m.strip() for m in settings.tier_preferences_cheap.split(",")],
    }


# -- Effectiveness matrix -----------------------------------------------------

async def _get_effectiveness_matrix() -> dict:
    """Read effectiveness matrix from Redis (5s cache).

    Returns dict of "model:task_type" -> {"avg_score": float, "sample_count": int}.
    Empty dict if not available yet (cold start).
    """
    global _effectiveness_cache, _effectiveness_cache_ts
    now = time.monotonic()
    if _effectiveness_cache is not None and (now - _effectiveness_cache_ts) < _CACHE_TTL:
        return _effectiveness_cache

    try:
        from .registry import _get_strategy_redis
        r = await _get_strategy_redis()
        raw = await r.get("nova:cache:model_effectiveness")
        _effectiveness_cache = json.loads(raw) if raw else {}
    except Exception:
        _effectiveness_cache = {}

    _effectiveness_cache_ts = now
    return _effectiveness_cache
