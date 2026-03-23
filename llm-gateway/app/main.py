"""Nova LLM Gateway — main entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nova_contracts.logging import configure_logging

from app.config import settings
from app.discovery import discovery_router
from app.health import health_router
from app.openai_router import openai_router
from app.router import router

configure_logging("llm-gateway", settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("LLM Gateway starting")
    # Set API keys from config into LiteLLM env
    import os
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    # Auto-register any Ollama models that are pulled but not in the registry
    try:
        from app.registry import sync_ollama_models
        added = await sync_ollama_models()
        if added:
            log.info("Synced %d Ollama model(s) into registry", added)
    except Exception as e:
        log.warning("Failed to sync Ollama models at startup: %s", e)

    # Probe vLLM/sglang at startup so they appear as available in the catalog
    try:
        from app.registry import sync_vllm_models
        added = await sync_vllm_models()
        if added:
            log.info("Synced %d vLLM model(s) into registry", added)
    except Exception as e:
        log.debug("vLLM not available at startup: %s", e)

    log.info("LLM Gateway ready")
    yield
    log.info("LLM Gateway shutting down")
    from app.rate_limiter import close as close_rate_limiter
    from app.response_cache import close as close_response_cache
    await close_rate_limiter()
    await close_response_cache()


app = FastAPI(
    title="Nova LLM Gateway",
    version="0.1.0",
    description="ModelProvider abstraction layer — route any model request to any provider",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(health_router, prefix="/v1")  # also expose at /v1/health/* for dashboard proxy
app.include_router(discovery_router, prefix="/v1")  # /v1/models/discover, /v1/models/ollama/*
app.include_router(router)
app.include_router(openai_router)  # mounts at /v1/chat/completions, /v1/models
