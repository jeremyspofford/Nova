"""Voice API endpoints — transcribe audio, synthesize speech, list voices."""
from __future__ import annotations

import json
import logging
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException, Response
from pydantic import BaseModel

from app.config import settings
from app.providers import get_stt_provider, get_tts_provider

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB Whisper API limit


# ── Admin secret resolver (Redis-backed, env fallback) ───────────────────────
#
# The admin secret is rotatable at runtime via the orchestrator's
# /api/v1/admin/rotate-secret endpoint, which stores the current value in
# `nova:config:auth.admin_secret` on Redis db 1. This service re-reads that
# key on a 30s cadence. If Redis is unavailable or the key is unset we fall
# back to `settings.nova_admin_secret` (from .env).
#
# Escape hatch: `redis-cli -n 1 DEL nova:config:auth.admin_secret` forces
# every service to revert to the env fallback.

_ADMIN_SECRET_CACHE_TTL = 30  # seconds
_admin_secret_cache: dict[str, Any] = {"value": None, "ts": 0.0}
_config_redis = None


def _config_redis_url() -> str:
    """Redis URL targeting db1 (shared nova:config:* namespace)."""
    return settings.redis_url.rsplit("/", 1)[0] + "/1"


async def get_admin_secret() -> str:
    """Return the current admin secret — Redis-backed, env fallback."""
    now = _time.monotonic()
    if (
        now - _admin_secret_cache["ts"] < _ADMIN_SECRET_CACHE_TTL
        and _admin_secret_cache["value"] is not None
    ):
        return _admin_secret_cache["value"]

    value: str | None = None
    try:
        global _config_redis
        if _config_redis is None:
            import redis.asyncio as aioredis
            _config_redis = aioredis.from_url(_config_redis_url(), decode_responses=True)
        raw = await _config_redis.get("nova:config:auth.admin_secret")
        if raw:
            try:
                parsed = json.loads(raw)
                value = parsed if isinstance(parsed, str) and parsed else raw
            except (json.JSONDecodeError, TypeError):
                value = raw
    except Exception:
        log.debug("Failed to read admin secret from Redis, using .env fallback")

    if not value:
        value = settings.nova_admin_secret

    _admin_secret_cache["value"] = value
    _admin_secret_cache["ts"] = now
    return value


# ── Auth dependency ──────────────────────────────────────────────────────────

async def require_auth(request: Request):
    """Auth check — same pattern as all Nova services.

    When REQUIRE_AUTH is true, validates X-Admin-Secret or Authorization header.
    When false (dev mode), allows all requests.
    """
    if not settings.require_auth:
        return

    admin_secret = request.headers.get("X-Admin-Secret", "")
    auth_header = request.headers.get("Authorization", "")

    current_secret = await get_admin_secret()
    if admin_secret and admin_secret == current_secret:
        return

    if auth_header.startswith("Bearer sk-nova-"):
        # In production, validate against orchestrator. For v1, accept any sk-nova- token
        # when admin secret is also set (trusted internal network).
        if current_secret:
            return

    raise HTTPException(401, "Authentication required")


# ── Request models ───────────────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "nova"
    model: str = "tts-1"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    format: str = Form("webm"),
    _auth=Depends(require_auth),
):
    """Transcribe audio to text via configured STT provider."""
    provider = _get_stt_or_503()

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "No audio provided")
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Audio file too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)")

    try:
        result = await provider.transcribe(audio_bytes, format=format, language=language)
    except Exception as e:
        log.warning("STT transcription failed: %s", e)
        raise HTTPException(500, f"Transcription failed: {e}")

    # Silence/hallucination guard: Whisper hallucinates on silent audio
    if result.confidence < 0.4 and result.duration_ms < 1000:
        log.info(
            "Silence detected (confidence=%.2f, duration=%dms), returning empty",
            result.confidence, result.duration_ms,
        )
        result.text = ""

    return {
        "text": result.text,
        "language": result.language,
        "duration_ms": result.duration_ms,
        "confidence": result.confidence,
        "speaker_id": result.speaker_id,
    }


@router.post("/synthesize")
async def synthesize(
    req: SynthesizeRequest,
    _auth=Depends(require_auth),
):
    """Convert text to speech via configured TTS provider. Returns MP3 audio."""
    provider = _get_tts_or_503()

    if not req.text or not req.text.strip():
        raise HTTPException(400, "Empty text")
    if len(req.text) > settings.max_tts_chars:
        raise HTTPException(400, f"Text too long (max {settings.max_tts_chars} chars)")

    try:
        audio_bytes = await provider.synthesize(
            text=req.text.strip(), voice=req.voice, model=req.model,
        )
    except Exception as e:
        log.warning("TTS synthesis failed: %s", e)
        raise HTTPException(500, f"Synthesis failed: {e}")

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.get("/voices")
async def list_voices(_auth=Depends(require_auth)):
    """List available voices for the configured TTS provider."""
    try:
        provider = get_tts_provider()
        voices = provider.available_voices()
    except Exception:
        voices = []

    return {
        "provider": settings.tts_provider,
        "voices": voices,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_stt_or_503():
    try:
        return get_stt_provider()
    except Exception as e:
        raise HTTPException(503, f"STT provider not configured: {e}")


def _get_tts_or_503():
    try:
        return get_tts_provider()
    except Exception as e:
        raise HTTPException(503, f"TTS provider not configured: {e}")
