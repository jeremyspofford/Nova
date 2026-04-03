"""
Baseline Mem0 wrapper — FastAPI app.

Wraps Mem0's Python SDK behind Nova's Memory Provider Interface
for benchmark comparison against Nova's native Engram memory.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("baseline-mem0")


def _build_mem0_config(use_gateway_fallback: bool = False) -> dict:
    """Build Mem0 config dict, optionally falling back to LLM gateway."""
    if use_gateway_fallback:
        # LLM gateway exposes OpenAI-compatible /v1/chat/completions and /v1/embeddings
        llm_config = {
            "provider": "openai",
            "config": {
                "model": "auto",
                "temperature": 0,
                "max_tokens": 2000,
                "openai_base_url": f"{settings.llm_gateway_url}/v1",
                "api_key": "not-needed",
            },
        }
        embedder_config = {
            "provider": "openai",
            "config": {
                "model": settings.ollama_embedding_model,
                "openai_base_url": f"{settings.llm_gateway_url}/v1",
                "api_key": "not-needed",
            },
        }
    else:
        llm_config = {
            "provider": "ollama",
            "config": {
                "model": settings.ollama_llm_model,
                "temperature": 0,
                "max_tokens": 2000,
                "ollama_base_url": settings.ollama_url,
            },
        }
        embedder_config = {
            "provider": "ollama",
            "config": {
                "model": settings.ollama_embedding_model,
                "ollama_base_url": settings.ollama_url,
            },
        }

    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": settings.mem0_collection_name,
                "embedding_model_dims": settings.embedding_dims,
                "path": settings.mem0_data_dir,
            },
        },
        "llm": llm_config,
        "embedder": embedder_config,
    }


async def _ollama_reachable() -> bool:
    """Check if Ollama is responding."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    from mem0 import Memory

    # Try Ollama first, fall back to LLM gateway
    use_fallback = not await _ollama_reachable()
    if use_fallback:
        log.warning(
            "Ollama unreachable at %s — falling back to LLM gateway at %s",
            settings.ollama_url,
            settings.llm_gateway_url,
        )
    else:
        log.info("Using Ollama at %s for Mem0 LLM + embeddings", settings.ollama_url)

    config = _build_mem0_config(use_gateway_fallback=use_fallback)
    try:
        app.state.mem0 = Memory.from_config(config)
        app.state.mem0_ready = True
        log.info("Mem0 initialized (collection=%s)", settings.mem0_collection_name)
    except Exception:
        log.exception("Failed to initialize Mem0 — service will start degraded")
        app.state.mem0 = None
        app.state.mem0_ready = False

    yield

    log.info("Baseline Mem0 wrapper shutting down")


app = FastAPI(
    title="Nova Baseline — Mem0",
    version="0.1.0",
    description="Mem0 SDK wrapped behind Nova's Memory Provider Interface for benchmarking",
    lifespan=lifespan,
)

# Import and mount routes after app is created
from app.routes import health_router, memory_router  # noqa: E402

app.include_router(health_router)
app.include_router(memory_router)
