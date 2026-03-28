"""
Dynamic model discovery — queries provider APIs to find actually-available models.

Results are cached in Redis (5-min TTL) and returned as a per-provider catalog
with auth method metadata so the dashboard can guide unconfigured users.

Endpoints:
    GET  /models/discover       — full provider catalog with discovered models
    GET  /models/resolve        — resolve "auto" to best available model
    GET  /models/ollama/pulled  — Ollama pulled models with size/details
    POST /models/ollama/pull    — pull a model into Ollama
    DELETE /models/ollama/{name} — delete a pulled Ollama model
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

log = logging.getLogger(__name__)

discovery_router = APIRouter(prefix="/models", tags=["discovery"])

_CACHE_TTL = 300  # 5 minutes
_DISCOVERY_TIMEOUT = 10.0  # per-provider timeout
_PULL_TIMEOUT = 600.0  # 10 minutes for model pulls

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


# ── Auth method metadata per provider ─────────────────────────────────────────

AUTH_METHODS: dict[str, list[str]] = {
    "ollama": ["Always available (local)"],
    "vllm": ["Available when vLLM is the active inference backend"],
    "claude-max": [
        "CLAUDE_CODE_OAUTH_TOKEN env var",
        "~/.claude/.credentials.json (auto-detected on Linux)",
        "macOS Keychain (auto-detected)",
    ],
    "chatgpt": [
        "CHATGPT_ACCESS_TOKEN env var",
        "~/.codex/auth.json (auto-detected after `codex login`)",
    ],
    "groq": ["GROQ_API_KEY env var — get free at console.groq.com"],
    "gemini": [
        "GEMINI_API_KEY env var — get free at aistudio.google.com",
        "gcloud ADC (~/.config/gcloud) — set GEMINI_USE_ADC=true",
    ],
    "cerebras": ["CEREBRAS_API_KEY env var — get free at cloud.cerebras.ai"],
    "openrouter": ["OPENROUTER_API_KEY env var — get free at openrouter.ai"],
    "github": ["GITHUB_TOKEN env var — any GitHub PAT with Models permission"],
    "anthropic": ["ANTHROPIC_API_KEY env var — console.anthropic.com"],
    "openai": ["OPENAI_API_KEY env var — platform.openai.com"],
}


# ── Response models ───────────────────────────────────────────────────────────

class DiscoveredModel(BaseModel):
    id: str
    registered: bool = False


class ProviderModelList(BaseModel):
    slug: str
    name: str
    type: str  # local | subscription | free | paid
    available: bool
    auth_methods: list[str]
    models: list[DiscoveredModel]


class OllamaPulledModel(BaseModel):
    name: str
    size: int  # bytes
    parameter_size: str
    quantization_level: str
    digest: str
    modified_at: str


class PullRequest(BaseModel):
    name: str


# ── Auto-registration helper ──────────────────────────────────────────────────

def _ensure_registered(model_id: str, provider: "ModelProvider") -> None:
    """Register a discovered model in MODEL_REGISTRY if not already present.

    This ensures that dynamically discovered models (from provider APIs) are
    routable, not just visible.  The provider's own auth gating guarantees we
    only register models the user actually has access to.
    """
    from app.registry import MODEL_REGISTRY, DEFAULT_MODEL_KEY
    if model_id not in MODEL_REGISTRY and model_id != DEFAULT_MODEL_KEY:
        MODEL_REGISTRY[model_id] = provider
        log.debug("Auto-registered discovered model: %s", model_id)


# ── Per-provider discovery coroutines ─────────────────────────────────────────

async def _discover_ollama() -> list[DiscoveredModel]:
    """List pulled Ollama models via /api/tags."""
    from app.registry import get_ollama_base_url
    try:
        ollama_url = await get_ollama_base_url()
        async with httpx.AsyncClient(base_url=ollama_url, timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [
                DiscoveredModel(id=m["name"], registered=True)
                for m in data.get("models", [])
            ]
    except Exception as e:
        log.debug("Ollama discovery failed: %s", e)
        return []


async def _discover_vllm() -> list[DiscoveredModel]:
    """Discover models from a running vLLM server."""
    models = []
    try:
        from app.registry import _get_redis_config
        url = await _get_redis_config("inference.url", "") or "http://nova-vllm:8000"
        backend = await _get_redis_config("inference.backend", "ollama")
        if backend != "vllm":
            return []

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{url}/v1/models")
            if r.status_code == 200:
                data = r.json()
                from app.registry import _vllm
                for m in data.get("data", []):
                    model_id = m.get("id", "")
                    if model_id:
                        _ensure_registered(model_id, _vllm)
                        models.append(DiscoveredModel(id=model_id, registered=True))
    except Exception as e:
        log.debug("vLLM discovery failed: %s", e)
    return models


async def _discover_groq() -> list[DiscoveredModel]:
    """List available Groq models via OpenAI-compatible /models endpoint."""
    if not settings.groq_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _groq
            models = []
            for m in data.get("data", []):
                if not m.get("active", True):
                    continue
                model_id = f"groq/{m['id']}"
                _ensure_registered(model_id, _groq)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("Groq discovery failed: %s", e)
        return []


async def _discover_anthropic() -> list[DiscoveredModel]:
    """List available Anthropic models."""
    if not settings.anthropic_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _litellm
            models = []
            for m in data.get("data", []):
                model_id = m["id"]
                _ensure_registered(model_id, _litellm)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("Anthropic discovery failed: %s", e)
        return []


async def _discover_openai() -> list[DiscoveredModel]:
    """List available OpenAI models."""
    if not settings.openai_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _litellm
            # Filter to chat models only (skip embeddings, tts, etc.)
            chat_prefixes = ("gpt-", "o1", "o3", "o4", "chatgpt-")
            models = []
            for m in data.get("data", []):
                if not any(m["id"].startswith(p) for p in chat_prefixes):
                    continue
                model_id = m["id"]
                _ensure_registered(model_id, _litellm)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("OpenAI discovery failed: %s", e)
        return []


async def _discover_openrouter() -> list[DiscoveredModel]:
    """List free OpenRouter models (no auth required)."""
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _openrouter
            # Only show free models to keep the list manageable
            free_models = [
                m for m in data.get("data", [])
                if ":free" in m.get("id", "")
            ][:30]  # cap at 30
            models = []
            for m in free_models:
                model_id = f"openrouter/{m['id']}"
                _ensure_registered(model_id, _openrouter)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("OpenRouter discovery failed: %s", e)
        return []


async def _discover_gemini() -> list[DiscoveredModel]:
    """List available Gemini models."""
    if not settings.gemini_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.gemini_api_key}",
            )
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _gemini
            models = []
            for m in data.get("models", []):
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                model_id = f"gemini/{m['name'].removeprefix('models/')}"
                _ensure_registered(model_id, _gemini)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("Gemini discovery failed: %s", e)
        return []


async def _discover_github() -> list[DiscoveredModel]:
    """List available GitHub Models."""
    if not settings.github_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(
                "https://models.github.com/v1/models",
                headers={"Authorization": f"Bearer {settings.github_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            from app.registry import _github
            models = []
            for m in data.get("data", data):
                if not isinstance(m, dict):
                    continue
                model_id = f"github/{m['id']}"
                _ensure_registered(model_id, _github)
                models.append(DiscoveredModel(id=model_id, registered=True))
            return models
    except Exception as e:
        log.debug("GitHub Models discovery failed: %s", e)
        return []


async def _discover_from_model_map(slug: str) -> list[DiscoveredModel]:
    """For providers without listing APIs (Claude Max, ChatGPT, Cerebras),
    return models from the provider's own _MODEL_MAP or registry entries."""
    if slug == "claude-max":
        from app.providers.claude_subscription_provider import _MODEL_MAP
        from app.registry import _claude_subscription
        models = []
        for k in _MODEL_MAP:
            if k.startswith("claude-max/"):
                _ensure_registered(k, _claude_subscription)
                models.append(DiscoveredModel(id=k, registered=True))
        return models
    elif slug == "chatgpt":
        from app.providers.chatgpt_subscription_provider import _MODEL_MAP
        from app.registry import _chatgpt_subscription
        models = []
        for k in _MODEL_MAP:
            if k.startswith("chatgpt/"):
                _ensure_registered(k, _chatgpt_subscription)
                models.append(DiscoveredModel(id=k, registered=True))
        return models
    elif slug == "cerebras":
        from app.registry import MODEL_REGISTRY
        return [
            DiscoveredModel(id=k, registered=True)
            for k in MODEL_REGISTRY
            if k.startswith("cerebras/")
        ]
    return []


# ── Provider catalog builder ─────────────────────────────────────────────────

_PROVIDER_META = [
    {"slug": "ollama",      "name": "Ollama",           "type": "local"},
    {"slug": "vllm",        "name": "vLLM",             "type": "local"},
    {"slug": "claude-max",  "name": "Claude Max/Pro",   "type": "subscription"},
    {"slug": "anthropic",   "name": "Anthropic API",    "type": "paid"},
    {"slug": "openai",      "name": "OpenAI API",       "type": "paid"},
    {"slug": "chatgpt",     "name": "ChatGPT Plus/Pro", "type": "subscription"},
    {"slug": "groq",        "name": "Groq",             "type": "free"},
    {"slug": "gemini",      "name": "Gemini",           "type": "free"},
    {"slug": "cerebras",    "name": "Cerebras",         "type": "free"},
    {"slug": "openrouter",  "name": "OpenRouter",       "type": "free"},
    {"slug": "github",      "name": "GitHub Models",    "type": "free"},
]

# Maps slug → discovery coroutine
_DISCOVERY_FNS: dict[str, Any] = {
    "ollama": _discover_ollama,
    "vllm": _discover_vllm,
    "groq": _discover_groq,
    "anthropic": _discover_anthropic,
    "openai": _discover_openai,
    "openrouter": _discover_openrouter,
    "gemini": _discover_gemini,
    "github": _discover_github,
    # These use _MODEL_MAP instead of API calls
    "claude-max": lambda: _discover_from_model_map("claude-max"),
    "chatgpt": lambda: _discover_from_model_map("chatgpt"),
    "cerebras": lambda: _discover_from_model_map("cerebras"),
}


async def _is_provider_available(slug: str) -> bool:
    """Check if a provider has credentials configured."""
    from app.providers.claude_subscription_provider import discover_claude_oauth_token
    from app.providers.chatgpt_subscription_provider import discover_chatgpt_token

    if slug == "vllm":
        # Must check Redis directly — the in-memory health flag starts False
        # and only flips after actual inference requests.
        from app.registry import _get_redis_config
        backend = await _get_redis_config("inference.backend", "ollama")
        return backend == "vllm"

    checks = {
        "ollama": lambda: True,
        "claude-max": lambda: bool(discover_claude_oauth_token()),
        "chatgpt": lambda: bool(discover_chatgpt_token()),
        "groq": lambda: bool(settings.groq_api_key),
        "gemini": lambda: bool(settings.gemini_api_key or settings.gemini_use_adc),
        "cerebras": lambda: bool(settings.cerebras_api_key),
        "openrouter": lambda: bool(settings.openrouter_api_key),
        "github": lambda: bool(settings.github_token),
        "anthropic": lambda: bool(settings.anthropic_api_key),
        "openai": lambda: bool(settings.openai_api_key),
    }
    try:
        return checks.get(slug, lambda: False)()
    except Exception:
        return False


async def _discover_provider(slug: str) -> list[DiscoveredModel]:
    """Run discovery for a single provider, with Redis caching."""
    cache_key = f"nova:model_catalog:{slug}"

    # Try cache first
    try:
        r = await _get_redis()
        cached = await r.get(cache_key)
        if cached:
            return [DiscoveredModel(**m) for m in json.loads(cached)]
    except Exception:
        pass

    # Run discovery
    fn = _DISCOVERY_FNS.get(slug)
    if not fn:
        return []

    try:
        models = await asyncio.wait_for(fn(), timeout=_DISCOVERY_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("Discovery timeout for %s", slug)
        return []
    except Exception as e:
        log.warning("Discovery failed for %s: %s", slug, e)
        return []

    # Cache result
    try:
        r = await _get_redis()
        await r.set(cache_key, json.dumps([m.model_dump() for m in models]), ex=_CACHE_TTL)
    except Exception:
        pass

    return models


async def discover_all() -> list[ProviderModelList]:
    """Run all provider discoveries concurrently and return the full catalog."""
    tasks = {
        meta["slug"]: _discover_provider(meta["slug"])
        for meta in _PROVIDER_META
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    catalog = []
    for meta, result in zip(_PROVIDER_META, results):
        slug = meta["slug"]
        available = await _is_provider_available(slug)
        models = result if isinstance(result, list) else []

        catalog.append(ProviderModelList(
            slug=slug,
            name=meta["name"],
            type=meta["type"],
            available=available,
            auth_methods=AUTH_METHODS.get(slug, []),
            models=models if available else [],
        ))

    return catalog


# ── Auto-resolve: pick best available model ───────────────────────────────────

# Quality-ranked preference list for general-purpose chat.
# Each entry: (model_id, provider_slug, requires_ollama_check)
_AUTO_PREFERENCE: list[tuple[str, str, bool]] = [
    ("claude-sonnet-4-6",              "anthropic",   False),
    ("claude-max/claude-sonnet-4-6",   "claude-max",  False),
    ("gpt-4o",                         "openai",      False),
    ("chatgpt/gpt-4o",                 "chatgpt",     False),
    ("gemini/gemini-2.5-flash",        "gemini",      False),
    ("groq/llama-3.3-70b-versatile",   "groq",        False),
    ("claude-haiku-4-5-20251001",      "anthropic",   False),
    ("claude-max/claude-haiku-4-5",    "claude-max",  False),
    ("chatgpt/gpt-4o-mini",           "chatgpt",     False),
    ("github/gpt-4o-mini",            "github",      False),
    ("cerebras/llama3.1-8b",           "cerebras",    False),
]

_FALLBACK_MODEL = "llama3.2"

# Module-level cache for resolve result
_resolve_cache: dict[str, tuple[str, str, float]] = {}  # "resolve" -> (model, source, timestamp)
_RESOLVE_CACHE_TTL = 30.0  # seconds


def _best_ollama_model() -> str | None:
    """Return the best pulled Ollama model by parameter count (sync-safe, uses cached catalog)."""
    import re

    # Try to read from the cached discovery result
    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    # We can't do async here easily, so check the Redis cache synchronously
    # Instead, use the in-memory catalog approach — check _OLLAMA_MODELS from registry
    from app.registry import MODEL_REGISTRY, _OLLAMA_MODELS

    if not _OLLAMA_MODELS:
        return None

    # Parse parameter sizes from known model names for ranking
    def _param_score(name: str) -> float:
        """Rough parameter count from model name for ranking."""
        # Match patterns like "70b", "8b", "3b", "1.5b"
        m = re.search(r'(\d+\.?\d*)b', name.lower())
        if m:
            return float(m.group(1))
        # Known sizes for common models without size in name
        known = {"deepseek-r1": 7, "mistral": 7, "phi4": 14, "gemma3": 12}
        for prefix, size in known.items():
            if name.startswith(prefix):
                return size
        return 3  # default assumption

    # Filter out embedding models and pick the largest
    candidates = [m for m in _OLLAMA_MODELS if "embed" not in m.lower()]
    if not candidates:
        return None

    # Sort by param count (desc), then alphabetically for deterministic tiebreak
    candidates.sort(key=lambda m: (-_param_score(m), m))
    return candidates[0]


async def resolve_auto_model() -> str:
    """Iterate the preference list and return the first model whose provider is available.
    Falls back to preferred local model, best Ollama model, then llama3.2."""
    for model_id, slug, _ in _AUTO_PREFERENCE:
        if await _is_provider_available(slug):
            return model_id

    # Check if user has a preferred local model configured
    try:
        from app.registry import _get_redis_config, _OLLAMA_MODELS
        preferred = await _get_redis_config("llm.preferred_local_model", "")
        if preferred and preferred in _OLLAMA_MODELS:
            return preferred
    except Exception:
        pass

    # Fall back to largest pulled Ollama model
    best_local = _best_ollama_model()
    if best_local:
        return best_local

    return _FALLBACK_MODEL


class ResolveResponse(BaseModel):
    model: str
    source: str  # "auto" or "explicit"


@discovery_router.get("/resolve")
async def resolve_model() -> ResolveResponse:
    """Resolve the default chat model. If set to 'auto', picks the best available model."""
    import time as _time

    # Check cache
    cached = _resolve_cache.get("resolve")
    if cached:
        model, source, ts = cached
        if (_time.monotonic() - ts) < _RESOLVE_CACHE_TTL:
            return ResolveResponse(model=model, source=source)

    # Read configured default from Redis
    from app.registry import _get_redis_config
    configured = await _get_redis_config("llm.default_chat_model", "auto")

    if configured == "auto":
        model = await resolve_auto_model()
        source = "auto"
    else:
        model = configured
        source = "explicit"

    _resolve_cache["resolve"] = (model, source, _time.monotonic())
    return ResolveResponse(model=model, source=source)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@discovery_router.get("/discover")
async def discover_models(refresh: bool = False) -> list[ProviderModelList]:
    """Discover all available models across all providers."""
    if refresh:
        # Invalidate cache
        try:
            r = await _get_redis()
            keys = [f"nova:model_catalog:{m['slug']}" for m in _PROVIDER_META]
            await r.delete(*keys)
        except Exception:
            pass

    return await discover_all()


@discovery_router.get("/ollama/pulled")
async def get_ollama_pulled() -> list[OllamaPulledModel]:
    """List all models pulled into Ollama with size and quantization details."""
    from app.registry import get_ollama_base_url
    try:
        ollama_url = await get_ollama_base_url()
        async with httpx.AsyncClient(base_url=ollama_url, timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}")

    models = []
    for m in data.get("models", []):
        details = m.get("details", {})
        models.append(OllamaPulledModel(
            name=m["name"],
            size=m.get("size", 0),
            parameter_size=details.get("parameter_size", ""),
            quantization_level=details.get("quantization_level", ""),
            digest=m.get("digest", "")[:12],
            modified_at=m.get("modified_at", ""),
        ))

    return models


@discovery_router.post("/ollama/pull")
async def pull_ollama_model(req: PullRequest):
    """Pull a model into Ollama. Blocking — may take several minutes."""
    from app.registry import get_ollama_base_url
    try:
        ollama_url = await get_ollama_base_url()
        async with httpx.AsyncClient(base_url=ollama_url, timeout=_PULL_TIMEOUT) as client:
            resp = await client.post("/api/pull", json={"name": req.name, "stream": False})
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Pull timed out after {_PULL_TIMEOUT}s")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama pull failed: {e}")

    # Auto-register the pulled model
    from app.registry import sync_ollama_models
    await sync_ollama_models()

    # Invalidate Ollama discovery cache
    try:
        r = await _get_redis()
        await r.delete("nova:model_catalog:ollama")
    except Exception:
        pass

    return {"status": "ok", "model": req.name}


@discovery_router.delete("/ollama/{name:path}")
async def delete_ollama_model(name: str):
    """Delete a pulled Ollama model."""
    from app.registry import get_ollama_base_url
    try:
        ollama_url = await get_ollama_base_url()
        async with httpx.AsyncClient(base_url=ollama_url, timeout=30.0) as client:
            resp = await client.request("DELETE", "/api/delete", json={"name": name})
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
            resp.raise_for_status()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama delete failed: {e}")

    # Invalidate cache
    try:
        r = await _get_redis()
        await r.delete("nova:model_catalog:ollama")
    except Exception:
        pass

    return {"status": "ok", "model": name}
