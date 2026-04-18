"""Nova LLM Gateway — main entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nova_contracts.logging import configure_logging
from nova_worker_common.admin_secret import AdminSecretResolver
from nova_worker_common.service_auth import (
    TrustedNetworkMiddleware,
    create_admin_auth_dep,
    load_trusted_cidrs_from_env,
    parse_cidrs,
)

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
    from app.editor_tracker import close as close_editor_tracker
    await close_editor_tracker()
    from app.discovery import close_redis as close_discovery_redis
    from app.registry import close_strategy_redis
    await close_discovery_redis()
    await close_strategy_redis()
    await _admin_resolver.close()


app = FastAPI(
    title="Nova LLM Gateway",
    version="0.1.0",
    description="ModelProvider abstraction layer — route any model request to any provider",
    lifespan=lifespan,
)

# ── Auth (SEC-003) ───────────────────────────────────────────────────────────
# Service-level auth: trusted-network bypass (Docker internal, Tailscale, LAN)
# OR X-Admin-Secret. Health endpoints stay open for Docker healthchecks +
# dashboard startup probes. See nova_worker_common/service_auth.py.
_trusted_cidrs = parse_cidrs(settings.trusted_network_cidrs) if settings.trusted_network_cidrs else load_trusted_cidrs_from_env()
_admin_resolver = AdminSecretResolver(redis_url=settings.redis_url, fallback=settings.nova_admin_secret)
_admin_auth = create_admin_auth_dep(_admin_resolver)

app.add_middleware(TrustedNetworkMiddleware, trusted_cidrs=_trusted_cidrs)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health routes stay open — used by Docker healthcheck + dashboard startup screen.
app.include_router(health_router)
app.include_router(health_router, prefix="/v1")  # also expose at /v1/health/* for dashboard proxy
# All other routes require auth.
app.include_router(discovery_router, prefix="/v1", dependencies=[Depends(_admin_auth)])
app.include_router(router, dependencies=[Depends(_admin_auth)])
app.include_router(openai_router, dependencies=[Depends(_admin_auth)])
