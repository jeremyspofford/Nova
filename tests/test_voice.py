"""Integration tests for voice service.

Requires: docker compose --profile voice up
Tests that call paid APIs (transcribe, synthesize) are skipped unless OPENAI_API_KEY is set.
"""
import os
import httpx
import pytest

VOICE = os.getenv("NOVA_VOICE_URL", "http://localhost:8130")
HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.asyncio
async def test_voice_health_live():
    """Voice service liveness check."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.get(f"{VOICE}/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_voice_health_ready():
    """Voice service readiness reports provider availability."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.get(f"{VOICE}/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "stt_provider" in data
        assert "stt_available" in data
        assert "tts_provider" in data
        assert "tts_available" in data


@pytest.mark.asyncio
async def test_voice_list_voices():
    """GET /voices returns provider and voice list."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.get(f"{VOICE}/api/v1/voice/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "voices" in data
        assert isinstance(data["voices"], list)


@pytest.mark.asyncio
async def test_transcribe_no_audio():
    """POST /transcribe with no file returns 422."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.post(f"{VOICE}/api/v1/voice/transcribe")
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_empty_text():
    """POST /synthesize with empty text returns 400."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.post(
            f"{VOICE}/api/v1/voice/synthesize",
            json={"text": "", "voice": "nova", "model": "tts-1"},
        )
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_synthesize_text_too_long():
    """POST /synthesize with text exceeding max_tts_chars returns 400."""
    async with httpx.AsyncClient(timeout=5) as c:
        resp = await c.post(
            f"{VOICE}/api/v1/voice/synthesize",
            json={"text": "x" * 5000, "voice": "nova", "model": "tts-1"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_OPENAI, reason="OPENAI_API_KEY not set")
async def test_synthesize_returns_mp3():
    """POST /synthesize returns valid MP3 audio."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(
            f"{VOICE}/api/v1/voice/synthesize",
            json={"text": "Hello, this is Nova.", "voice": "nova", "model": "tts-1"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert len(resp.content) > 1000  # MP3 should be at least 1KB
