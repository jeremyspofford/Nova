"""
Dynamic model discovery — queries provider APIs to find actually-available models.

Results are cached in Redis (5-min TTL) and returned as a per-provider catalog
with auth method metadata so the dashboard can guide unconfigured users.

Endpoints:
    GET  /models/discover       — full provider catalog with discovered models
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
            from app.registry import MODEL_REGISTRY
            return [
                DiscoveredModel(
                    id=f"groq/{m['id']}",
                    registered=f"groq/{m['id']}" in MODEL_REGISTRY,
                )
                for m in data.get("data", [])
                if m.get("active", True)
            ]
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
            from app.registry import MODEL_REGISTRY
            return [
                DiscoveredModel(
                    id=m["id"],
                    registered=m["id"] in MODEL_REGISTRY,
                )
                for m in data.get("data", [])
            ]
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
            from app.registry import MODEL_REGISTRY
            # Filter to chat models only (skip embeddings, tts, etc.)
            chat_prefixes = ("gpt-", "o1", "o3", "o4", "chatgpt-")
            return [
                DiscoveredModel(
                    id=m["id"],
                    registered=m["id"] in MODEL_REGISTRY,
                )
                for m in data.get("data", [])
                if any(m["id"].startswith(p) for p in chat_prefixes)
            ]
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
            from app.registry import MODEL_REGISTRY
            # Only show free models to keep the list manageable
            free_models = [
                m for m in data.get("data", [])
                if ":free" in m.get("id", "")
            ][:30]  # cap at 30
            return [
                DiscoveredModel(
                    id=f"openrouter/{m['id']}",
                    registered=f"openrouter/{m['id']}" in MODEL_REGISTRY,
                )
                for m in free_models
            ]
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
            from app.registry import MODEL_REGISTRY
            return [
                DiscoveredModel(
                    id=f"gemini/{m['name'].removeprefix('models/')}",
                    registered=f"gemini/{m['name'].removeprefix('models/')}" in MODEL_REGISTRY,
                )
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
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
            from app.registry import MODEL_REGISTRY
            return [
                DiscoveredModel(
                    id=f"github/{m['id']}",
                    registered=f"github/{m['id']}" in MODEL_REGISTRY,
                )
                for m in data.get("data", data) if isinstance(m, dict)
            ]
    except Exception as e:
        log.debug("GitHub Models discovery failed: %s", e)
        return []


async def _discover_from_model_map(slug: str) -> list[DiscoveredModel]:
    """For providers without listing APIs (Claude Max, ChatGPT, Cerebras),
    return models from the provider's own _MODEL_MAP or registry entries."""
    from app.registry import MODEL_REGISTRY

    if slug == "claude-max":
        from app.providers.claude_subscription_provider import _MODEL_MAP
        return [
            DiscoveredModel(id=k, registered=k in MODEL_REGISTRY)
            for k in _MODEL_MAP
            if k.startswith("claude-max/")
        ]
    elif slug == "chatgpt":
        from app.providers.chatgpt_subscription_provider import _MODEL_MAP
        return [
            DiscoveredModel(id=k, registered=k in MODEL_REGISTRY)
            for k in _MODEL_MAP
            if k.startswith("chatgpt/")
        ]
    elif slug == "cerebras":
        return [
            DiscoveredModel(id=k, registered=True)
            for k in MODEL_REGISTRY
            if k.startswith("cerebras/")
        ]
    return []


# ── Provider catalog builder ─────────────────────────────────────────────────

_PROVIDER_META = [
    {"slug": "ollama",      "name": "Ollama",           "type": "local"},
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


def _is_provider_available(slug: str) -> bool:
    """Check if a provider has credentials configured."""
    from app.providers.claude_subscription_provider import discover_claude_oauth_token
    from app.providers.chatgpt_subscription_provider import discover_chatgpt_token

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
        available = _is_provider_available(slug)
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
