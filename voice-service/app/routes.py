"""Voice API endpoints — transcribe audio, synthesize speech, list voices."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, HTTPException, Response
from pydantic import BaseModel

from app.config import settings
from app.providers import get_stt_provider, get_tts_provider

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB Whisper API limit


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

    if admin_secret and admin_secret == settings.nova_admin_secret:
        return

    if auth_header.startswith("Bearer sk-nova-"):
        # In production, validate against orchestrator. For v1, accept any sk-nova- token
        # when admin secret is also set (trusted internal network).
        if settings.nova_admin_secret:
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
