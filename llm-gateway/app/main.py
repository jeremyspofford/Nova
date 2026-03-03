"""Nova LLM Gateway — main entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nova_contracts.logging import configure_logging

from app.config import settings
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
    log.info("LLM Gateway ready")
    yield
    log.info("LLM Gateway shutting down")


app = FastAPI(
    title="Nova LLM Gateway",
    version="0.1.0",
    description="ModelProvider abstraction layer — route any model request to any provider",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(router)
app.include_router(openai_router)  # mounts at /v1/chat/completions, /v1/models
