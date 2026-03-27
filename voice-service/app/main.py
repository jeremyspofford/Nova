"""Nova Voice Service — STT and TTS provider proxy."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

try:
    from nova_contracts.logging import configure_logging
    configure_logging("voice-service", settings.log_level)
except ImportError:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Voice service starting on http://0.0.0.0:%d", settings.service_port)
    yield
    log.info("Voice service shutting down")
    await close_redis()


app = FastAPI(
    title="Nova Voice Service",
    version="0.1.0",
    description="Speech-to-text and text-to-speech proxy",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    stt_available = bool(settings.openai_api_key) if settings.stt_provider == "openai" else False
    tts_available = bool(settings.openai_api_key) if settings.tts_provider == "openai" else False
    status = "ready" if (stt_available and tts_available) else "degraded"
    return {
        "status": status,
        "stt_provider": settings.stt_provider,
        "stt_available": stt_available,
        "tts_provider": settings.tts_provider,
        "tts_available": tts_available,
    }
