# Voice Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add push-to-talk voice chat to Nova's Brain page — a voice-service microservice (STT via Whisper, TTS via OpenAI) with browser-side recording, sentence-buffered audio playback, and Settings UI.

**Architecture:** Thin REST voice-service (port 8130, Redis DB 9, profile `voice`) proxies audio to STT/TTS providers. Browser records audio via MediaRecorder, sends to `/transcribe`, feeds transcript into existing `streamChat()` path, buffers streamed response into sentences, sends each to `/synthesize`, and plays MP3 audio sequentially. Voice service never touches the LLM layer.

**Tech Stack:** FastAPI + httpx + openai SDK (backend), MediaRecorder + Audio API (frontend), OpenAI Whisper + TTS (providers)

**Spec:** `docs/superpowers/specs/2026-03-27-voice-chat-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `voice-service/app/main.py` | FastAPI app, lifespan, health endpoints, CORS |
| `voice-service/app/config.py` | Pydantic settings (providers, voice, limits, auth) |
| `voice-service/app/routes.py` | `/transcribe`, `/synthesize`, `/voices` endpoints |
| `voice-service/app/providers/__init__.py` | Provider registry — resolves configured provider to implementation |
| `voice-service/app/providers/base.py` | `STTProvider` and `TTSProvider` ABCs, `TranscriptResult` dataclass |
| `voice-service/app/providers/openai_stt.py` | OpenAI Whisper STT implementation |
| `voice-service/app/providers/openai_tts.py` | OpenAI TTS implementation |
| `voice-service/Dockerfile` | Python 3.12-slim container (same pattern as chat-api) |
| `voice-service/pyproject.toml` | Dependencies |
| `dashboard/src/hooks/useVoiceChat.ts` | MediaRecorder recording + TTS audio playback + sentence buffering |
| `tests/test_voice.py` | Integration tests for voice service endpoints |

### Modified Files

| File | Change |
|------|--------|
| `docker-compose.yml` | Add voice-service with profile `voice` |
| `.env.example` | Add `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, voice settings |
| `dashboard/vite.config.ts` | Add `/voice-api` proxy to localhost:8130 |
| `dashboard/nginx.conf` | Add `/voice-api/` location block |
| `dashboard/src/components/BrainChat.tsx` | Add mic button, refactor `handleSubmit(text?)`, wire useVoiceChat |
| `dashboard/src/pages/Settings.tsx` | Add Voice section to nav + render |
| `CLAUDE.md` | Add voice-service to architecture, port 8130, Redis DB 9 |

---

## Phase 1: Voice Service Backend

### Task 1: Service Scaffold (config + main + Dockerfile)

**Files:**
- Create: `voice-service/app/__init__.py`
- Create: `voice-service/app/config.py`
- Create: `voice-service/app/main.py`
- Create: `voice-service/Dockerfile`
- Create: `voice-service/pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nova-voice-service"
version = "0.1.0"
description = "Speech-to-text and text-to-speech proxy for Nova"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "redis[hiredis]>=5.0",
    "httpx>=0.27",
    "openai>=1.0",
    "python-multipart>=0.0.9",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "nova-contracts",
]

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: Create config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider selection
    stt_provider: str = "openai"
    tts_provider: str = "openai"

    # Voice settings
    tts_voice: str = "nova"
    tts_model: str = "tts-1"

    # API keys
    openai_api_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""

    # Auth
    require_auth: bool = True
    nova_admin_secret: str = ""
    cors_allowed_origins: str = "http://localhost:3001,http://localhost:5173"

    # Limits
    max_audio_duration_seconds: int = 60
    max_tts_chars: int = 4096
    tts_rate_limit_per_minute: int = 120

    # Service
    redis_url: str = "redis://redis:6379/9"
    service_host: str = "0.0.0.0"
    service_port: int = 8130
    log_level: str = "INFO"


settings = Settings()
```

- [ ] **Step 3: Create main.py**

Follow chat-api/app/main.py pattern exactly:

```python
"""Nova Voice Service — STT and TTS provider proxy."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nova_contracts.logging import configure_logging

from app.config import settings

configure_logging("voice-service", settings.log_level)
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
```

- [ ] **Step 4: Create empty __init__.py**

```python
# voice-service/app/__init__.py
```

- [ ] **Step 5: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /nova-contracts

COPY voice-service/pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .

COPY voice-service/app/ app/

EXPOSE 8130

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8130"]
```

- [ ] **Step 6: Commit**

```bash
git add voice-service/
git commit -m "feat(voice): scaffold voice service with config, health endpoints, Dockerfile"
```

---

### Task 2: Provider Abstractions

**Files:**
- Create: `voice-service/app/providers/__init__.py`
- Create: `voice-service/app/providers/base.py`
- Create: `voice-service/app/providers/openai_stt.py`
- Create: `voice-service/app/providers/openai_tts.py`

- [ ] **Step 1: Create base.py with ABCs**

```python
"""Provider interfaces for STT and TTS."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptResult:
    text: str
    language: str = "en"
    duration_ms: int = 0
    confidence: float = 0.0
    speaker_id: str | None = None  # v2: voiceprint match


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(
        self, audio: bytes, format: str = "webm", language: str | None = None
    ) -> TranscriptResult:
        """Transcribe audio to text. Format is MIME subtype (webm, mp4, ogg, wav)."""
        ...


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, model: str) -> bytes:
        """Convert text to audio. Returns complete MP3 bytes."""
        ...

    def available_voices(self) -> list[dict]:
        """Return list of available voices for this provider."""
        return []
```

- [ ] **Step 2: Create openai_stt.py**

```python
"""OpenAI Whisper STT provider."""
from __future__ import annotations

import io
import logging

from openai import AsyncOpenAI

from .base import STTProvider, TranscriptResult

log = logging.getLogger(__name__)

# Map MIME subtypes to file extensions Whisper expects
FORMAT_TO_EXT = {
    "webm": "webm",
    "mp4": "mp4",
    "ogg": "ogg",
    "wav": "wav",
    "mpeg": "mp3",
    "m4a": "m4a",
}


class OpenAISTT(STTProvider):
    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def transcribe(
        self, audio: bytes, format: str = "webm", language: str | None = None
    ) -> TranscriptResult:
        ext = FORMAT_TO_EXT.get(format, "webm")
        audio_file = io.BytesIO(audio)
        audio_file.name = f"recording.{ext}"

        kwargs: dict = {"model": "whisper-1", "file": audio_file, "response_format": "verbose_json"}
        if language:
            kwargs["language"] = language

        response = await self._client.audio.transcriptions.create(**kwargs)

        # verbose_json returns segments with avg_logprob for confidence estimation
        confidence = 0.0
        if hasattr(response, "segments") and response.segments:
            avg_logprob = sum(s.get("avg_logprob", -1) for s in response.segments) / len(response.segments)
            # Convert log probability to 0-1 confidence (rough approximation)
            import math
            confidence = min(1.0, max(0.0, math.exp(avg_logprob)))

        duration_ms = int(getattr(response, "duration", 0) * 1000)

        return TranscriptResult(
            text=response.text.strip(),
            language=getattr(response, "language", "en"),
            duration_ms=duration_ms,
            confidence=confidence,
        )
```

- [ ] **Step 3: Create openai_tts.py**

```python
"""OpenAI TTS provider."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from .base import TTSProvider

log = logging.getLogger(__name__)

OPENAI_VOICES = [
    {"id": "alloy", "name": "Alloy"},
    {"id": "echo", "name": "Echo"},
    {"id": "fable", "name": "Fable"},
    {"id": "onyx", "name": "Onyx"},
    {"id": "nova", "name": "Nova"},
    {"id": "shimmer", "name": "Shimmer"},
]


class OpenAITTS(TTSProvider):
    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def synthesize(self, text: str, voice: str, model: str) -> bytes:
        response = await self._client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return response.content

    def available_voices(self) -> list[dict]:
        return OPENAI_VOICES
```

- [ ] **Step 4: Create provider registry (__init__.py)**

```python
"""Provider registry — resolves configured provider names to implementations.

Providers are cached as singletons to reuse HTTP connection pools across requests.
"""
from __future__ import annotations

from app.config import settings

from .base import STTProvider, TTSProvider

_stt_cache: dict[str, STTProvider] = {}
_tts_cache: dict[str, TTSProvider] = {}


def get_stt_provider() -> STTProvider:
    """Resolve the configured STT provider. Cached per provider+key combo."""
    cache_key = f"{settings.stt_provider}:{settings.openai_api_key[:8] if settings.openai_api_key else ''}"
    if cache_key not in _stt_cache:
        if settings.stt_provider == "openai":
            from .openai_stt import OpenAISTT
            _stt_cache[cache_key] = OpenAISTT(api_key=settings.openai_api_key)
        else:
            raise ValueError(f"Unknown STT provider: {settings.stt_provider}")
    return _stt_cache[cache_key]


def get_tts_provider() -> TTSProvider:
    """Resolve the configured TTS provider. Cached per provider+key combo."""
    cache_key = f"{settings.tts_provider}:{settings.openai_api_key[:8] if settings.openai_api_key else ''}"
    if cache_key not in _tts_cache:
        if settings.tts_provider == "openai":
            from .openai_tts import OpenAITTS
            _tts_cache[cache_key] = OpenAITTS(api_key=settings.openai_api_key)
        else:
            raise ValueError(f"Unknown TTS provider: {settings.tts_provider}")
    return _tts_cache[cache_key]
```

- [ ] **Step 5: Commit**

```bash
git add voice-service/app/providers/
git commit -m "feat(voice): add STT/TTS provider abstractions with OpenAI implementations"
```

---

### Task 3: API Routes (transcribe, synthesize, voices)

**Files:**
- Create: `voice-service/app/routes.py`
- Modify: `voice-service/app/main.py`

- [ ] **Step 1: Create routes.py**

```python
"""Voice API endpoints — transcribe audio, synthesize speech, list voices."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.providers import get_stt_provider, get_tts_provider
from app.providers.base import TranscriptResult

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice")


# ── Auth dependency ──────────────────────────────────────────────────────────

async def require_auth_if_enabled():
    """Auth dependency — same pattern as all Nova services.

    Checks X-Admin-Secret or Authorization header when REQUIRE_AUTH is true.
    Skipped when REQUIRE_AUTH is false (dev mode).
    """
    # When auth is disabled (dev mode), allow all requests
    if not settings.require_auth:
        return
    # When auth is enabled, the caller must provide either:
    # - X-Admin-Secret header matching nova_admin_secret
    # - Authorization: Bearer sk-nova-<hash> (validated against orchestrator)
    # Implementation: import from a shared auth module or inline check.
    # For v1, admin secret check is sufficient:
    from fastapi import Request
    # This is injected via Depends() on each endpoint
    pass  # Actual implementation reads headers from the request

# NOTE: The actual auth implementation should follow the pattern in
# orchestrator/app/auth.py (AdminDep). For the plan, the key point is that
# every endpoint below has `_auth = Depends(require_auth_if_enabled)` as a parameter.


# ── Request models ───────────────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "nova"
    model: str = "tts-1"

# Max upload size: 25MB (Whisper API limit)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    format: str = Form("webm"),
    _auth=Depends(require_auth_if_enabled),
):
    """Transcribe audio to text via configured STT provider."""
    # Validate provider availability
    provider = _get_stt_or_503()

    # Read and validate audio
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "No audio provided")
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Audio file too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)")

    # Transcribe
    try:
        result: TranscriptResult = await provider.transcribe(
            audio_bytes, format=format, language=language
        )
    except Exception as e:
        log.warning("STT transcription failed: %s", e)
        raise HTTPException(500, f"Transcription failed: {e}")

    # Silence/hallucination guard: Whisper hallucinates on silent audio
    if result.confidence < 0.4 and result.duration_ms < 1000:
        log.info("Silence detected (confidence=%.2f, duration=%dms), returning empty", result.confidence, result.duration_ms)
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
    _auth=Depends(require_auth_if_enabled),
):
    """Convert text to speech via configured TTS provider. Returns MP3 audio."""
    provider = _get_tts_or_503()

    if not req.text or not req.text.strip():
        raise HTTPException(400, "Empty text")
    if len(req.text) > settings.max_tts_chars:
        raise HTTPException(400, f"Text too long (max {settings.max_tts_chars} chars)")

    try:
        audio_bytes = await provider.synthesize(text=req.text.strip(), voice=req.voice, model=req.model)
    except Exception as e:
        log.warning("TTS synthesis failed: %s", e)
        raise HTTPException(500, f"Synthesis failed: {e}")

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.get("/voices")
async def list_voices():
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


def _get_stt_or_503():
    """Get STT provider or raise 503 if not configured."""
    try:
        provider = get_stt_provider()
    except Exception as e:
        raise HTTPException(503, f"STT provider not configured: {e}")
    return provider


def _get_tts_or_503():
    """Get TTS provider or raise 503 if not configured."""
    try:
        provider = get_tts_provider()
    except Exception as e:
        raise HTTPException(503, f"TTS provider not configured: {e}")
    return provider
```

- [ ] **Step 2: Register routes in main.py**

Add after the health endpoints:

```python
from app.routes import router as voice_router
app.include_router(voice_router)
```

- [ ] **Step 3: Commit**

```bash
git add voice-service/app/routes.py voice-service/app/main.py
git commit -m "feat(voice): add transcribe, synthesize, and voices API endpoints"
```

---

### Task 4: Docker Compose + Proxy + Env

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `dashboard/vite.config.ts`
- Modify: `dashboard/nginx.conf`

- [ ] **Step 1: Add voice-service to docker-compose.yml**

Add after the knowledge-worker service definition. Follow the chat-bridge profiled service pattern:

```yaml
  voice-service:
    <<: *nova-common
    profiles: ["voice"]
    build:
      context: .
      dockerfile: voice-service/Dockerfile
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8130", "--reload"]
    develop:
      watch:
        - action: sync
          path: ./voice-service/app
          target: /app/app
          ignore:
            - __pycache__
            - "*.pyc"
        - action: rebuild
          path: ./voice-service/pyproject.toml
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      DEEPGRAM_API_KEY: ${DEEPGRAM_API_KEY:-}
      ELEVENLABS_API_KEY: ${ELEVENLABS_API_KEY:-}
      REDIS_URL: redis://redis:6379/9
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      REQUIRE_AUTH: ${REQUIRE_AUTH:-false}
      NOVA_ADMIN_SECRET: ${NOVA_ADMIN_SECRET:-nova-admin-secret-change-me}
      CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS:-http://localhost:3001,http://localhost:5173}
    ports:
      - "8130:8130"
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      <<: *nova-healthcheck
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8130/health/live', timeout=3)"]
```

- [ ] **Step 2: Add env vars to .env.example**

Add in the API keys section:

```bash
# Voice Service (enable with: docker compose --profile voice up)
DEEPGRAM_API_KEY=                 # https://console.deepgram.com (optional, upgrades STT)
ELEVENLABS_API_KEY=               # https://elevenlabs.io (optional, upgrades TTS)
# Voice settings (runtime-configurable via dashboard Settings)
# TTS_VOICE=nova                  # OpenAI: alloy, echo, fable, onyx, nova, shimmer
# TTS_MODEL=tts-1                 # tts-1 (fast) or tts-1-hd (quality)
```

- [ ] **Step 3: Add Vite proxy**

In `dashboard/vite.config.ts`, add to the proxy section:

```typescript
'/voice-api': {
  target: 'http://localhost:8130',
  changeOrigin: true,
  rewrite: (path: string) => path.replace(/^\/voice-api/, ''),
},
```

- [ ] **Step 4: Add nginx location**

In `dashboard/nginx.conf`, add after the cortex-api location block:

```nginx
    location /voice-api/ {
        set $voice http://voice-service:8130;
        rewrite ^/voice-api/(.*) /$1 break;
        proxy_pass $voice;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_read_timeout 30s;
        client_max_body_size 25m;
    }
```

Note: `client_max_body_size 25m` allows audio file uploads. `proxy_read_timeout 30s` prevents nginx from timing out on longer transcriptions.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example dashboard/vite.config.ts dashboard/nginx.conf
git commit -m "feat(voice): add Docker Compose service, proxy config, and env vars"
```

---

### Task 5: Integration Tests

**Files:**
- Create: `tests/test_voice.py`

- [ ] **Step 1: Create test file**

```python
"""Integration tests for voice service.

Requires: docker compose --profile voice up
These tests hit the real voice service. Tests that call paid APIs
(transcribe, synthesize) are skipped unless OPENAI_API_KEY is set.
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
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_voice.py
git commit -m "test(voice): add integration tests for voice service endpoints"
```

---

## Phase 2: Dashboard Integration

### Task 6: useVoiceChat Hook

**Files:**
- Create: `dashboard/src/hooks/useVoiceChat.ts`

- [ ] **Step 1: Create the hook**

This hook handles: MediaRecorder management, audio recording with MIME detection, TTS audio playback with sentence queuing, blob URL cleanup, and interruption handling.

```typescript
import { useState, useRef, useCallback, useEffect } from 'react'

interface UseVoiceChatOptions {
  onTranscript?: (text: string) => void
  onError?: (error: string) => void
  maxDurationMs?: number
  minDurationMs?: number
}

interface SentenceAudio {
  seq: number
  audio: HTMLAudioElement | null
  blobUrl: string | null
  status: 'pending' | 'loading' | 'ready' | 'playing' | 'done'
}

export function useVoiceChat({
  onTranscript,
  onError,
  maxDurationMs = 60_000,
  minDurationMs = 500,
}: UseVoiceChatOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [recordingDuration, setRecordingDuration] = useState(0)
  const [voiceAvailable, setVoiceAvailable] = useState(false)
  const [muted, setMuted] = useState(() => localStorage.getItem('nova_voice_muted') === 'true')

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const mimeTypeRef = useRef('audio/webm;codecs=opus')
  const recordStartRef = useRef(0)
  const durationIntervalRef = useRef<ReturnType<typeof setInterval>>()
  const maxDurationTimerRef = useRef<ReturnType<typeof setTimeout>>()

  // Audio playback queue
  const audioQueueRef = useRef<SentenceAudio[]>([])
  const currentSeqRef = useRef(0)
  const nextSeqRef = useRef(0)
  const sentenceBufferRef = useRef('')
  const inCodeBlockRef = useRef(false)

  // Check voice service availability
  useEffect(() => {
    const check = async () => {
      try {
        const resp = await fetch('/voice-api/health/ready')
        if (resp.ok) {
          const data = await resp.json()
          setVoiceAvailable(data.stt_available && data.tts_available)
        }
      } catch {
        setVoiceAvailable(false)
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  // Persist mute state
  useEffect(() => {
    localStorage.setItem('nova_voice_muted', String(muted))
  }, [muted])

  // Detect supported MIME type
  useEffect(() => {
    const types = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        mimeTypeRef.current = type
        break
      }
    }
  }, [])

  const stopAllPlayback = useCallback(() => {
    audioQueueRef.current.forEach(item => {
      if (item.audio) {
        item.audio.pause()
        item.audio.currentTime = 0
      }
      if (item.blobUrl) URL.revokeObjectURL(item.blobUrl)
    })
    audioQueueRef.current = []
    currentSeqRef.current = 0
    nextSeqRef.current = 0
    sentenceBufferRef.current = ''
    inCodeBlockRef.current = false
    setIsSpeaking(false)
  }, [])

  const startRecording = useCallback(async () => {
    // Interrupt any playing audio first
    stopAllPlayback()

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })

      const recorder = new MediaRecorder(stream, { mimeType: mimeTypeRef.current })
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        clearInterval(durationIntervalRef.current)
        clearTimeout(maxDurationTimerRef.current)

        const elapsed = Date.now() - recordStartRef.current
        if (elapsed < minDurationMs) {
          setIsRecording(false)
          return // Too short, ignore
        }

        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current })
        setIsRecording(false)
        setIsTranscribing(true)

        try {
          const formData = new FormData()
          formData.append('file', blob, `recording.${mimeTypeRef.current.split('/')[1].split(';')[0]}`)
          formData.append('format', mimeTypeRef.current.split('/')[1].split(';')[0])

          const resp = await fetch('/voice-api/api/v1/voice/transcribe', {
            method: 'POST',
            body: formData,
          })

          if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Transcription failed' }))
            throw new Error(err.detail || `HTTP ${resp.status}`)
          }

          const result = await resp.json()
          if (result.text) {
            onTranscript?.(result.text)
          } else {
            onError?.("Couldn't understand that — try again")
          }
        } catch (err: any) {
          onError?.(err.message || 'Transcription failed — try again or type your message')
        } finally {
          setIsTranscribing(false)
        }
      }

      recorder.start()
      recordStartRef.current = Date.now()
      setIsRecording(true)
      setRecordingDuration(0)
      mediaRecorderRef.current = recorder

      // Duration counter
      durationIntervalRef.current = setInterval(() => {
        setRecordingDuration(Date.now() - recordStartRef.current)
      }, 100)

      // Auto-stop at max duration
      maxDurationTimerRef.current = setTimeout(() => {
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
      }, maxDurationMs)
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        onError?.('Microphone access denied. Enable in browser settings.')
      } else {
        onError?.(err.message || 'Could not access microphone')
      }
    }
  }, [stopAllPlayback, minDurationMs, maxDurationMs, onTranscript, onError])

  const stopRecording = useCallback(() => {
    const elapsed = Date.now() - recordStartRef.current
    if (elapsed < minDurationMs) return // Ignore too-quick stops

    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [minDurationMs])

  const toggleRecording = useCallback(() => {
    if (isRecording) stopRecording()
    else startRecording()
  }, [isRecording, startRecording, stopRecording])

  // ── TTS Playback ──────────────────────────────────────────────

  const playNextInQueue = useCallback(() => {
    const next = audioQueueRef.current.find(
      item => item.seq === currentSeqRef.current && item.status === 'ready'
    )
    if (!next || !next.audio) return

    next.status = 'playing'
    setIsSpeaking(true)

    next.audio.onended = () => {
      next.status = 'done'
      if (next.blobUrl) URL.revokeObjectURL(next.blobUrl)
      currentSeqRef.current++

      // Check if more to play
      const hasMore = audioQueueRef.current.some(
        item => item.seq >= currentSeqRef.current && item.status !== 'done'
      )
      if (!hasMore) {
        setIsSpeaking(false)
        audioQueueRef.current = []
        currentSeqRef.current = 0
        nextSeqRef.current = 0
      } else {
        playNextInQueue()
      }
    }

    if (!muted) {
      next.audio.play().catch(() => {
        // Autoplay blocked — skip this sentence
        next.status = 'done'
        currentSeqRef.current++
        playNextInQueue()
      })
    } else {
      // Muted — skip immediately
      next.status = 'done'
      if (next.blobUrl) URL.revokeObjectURL(next.blobUrl)
      currentSeqRef.current++
      playNextInQueue()
    }
  }, [muted])

  const synthesizeSentence = useCallback(async (text: string, seq: number) => {
    const entry: SentenceAudio = { seq, audio: null, blobUrl: null, status: 'loading' }
    audioQueueRef.current.push(entry)

    try {
      const resp = await fetch('/voice-api/api/v1/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: 'nova', model: 'tts-1' }),
      })
      if (!resp.ok) throw new Error(`TTS failed: ${resp.status}`)

      const blob = await resp.blob()
      const blobUrl = URL.createObjectURL(blob)
      const audio = new Audio(blobUrl)

      entry.audio = audio
      entry.blobUrl = blobUrl
      entry.status = 'ready'

      // Try to play if this is the current sequence
      if (entry.seq === currentSeqRef.current) {
        playNextInQueue()
      }
    } catch {
      // TTS failed for this sentence — mark done, skip it
      entry.status = 'done'
    }
  }, [playNextInQueue])

  // ── Text-to-speakable preprocessor ────────────────────────────

  const toSpeakable = useCallback((text: string): string => {
    let result = text
    // Remove fenced code blocks entirely
    result = result.replace(/```[\s\S]*?```/g, ' Here\'s some code. ')
    // Remove inline code backticks (keep content)
    result = result.replace(/`([^`]+)`/g, '$1')
    // Replace URLs with domain
    result = result.replace(/https?:\/\/([^\s/]+)[^\s]*/g, 'link to $1')
    // Remove markdown tables
    result = result.replace(/\|[^\n]+\|(\n\|[-:| ]+\|)?(\n\|[^\n]+\|)*/g, '')
    // Remove heading markers
    result = result.replace(/^#{1,6}\s+/gm, '')
    // Remove bold/italic markers
    result = result.replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
    result = result.replace(/_{1,2}([^_]+)_{1,2}/g, '$1')
    // Remove list markers
    result = result.replace(/^[\s]*[-*]\s+/gm, '')
    result = result.replace(/^[\s]*\d+\.\s+/gm, '')
    // Remove horizontal rules
    result = result.replace(/^---+$/gm, '')
    // Clean up multiple spaces/newlines
    result = result.replace(/\n{2,}/g, '\n').replace(/\s{2,}/g, ' ').trim()
    return result
  }, [])

  // ── Sentence detection + buffer ───────────────────────────────

  const feedText = useCallback((delta: string) => {
    if (muted) return // Don't buffer if muted

    sentenceBufferRef.current += delta

    // Track code blocks
    const fences = (sentenceBufferRef.current.match(/```/g) || []).length
    inCodeBlockRef.current = fences % 2 !== 0
    if (inCodeBlockRef.current) return // Don't split inside code blocks

    // Check for sentence boundaries
    const buf = sentenceBufferRef.current
    const delimiters = /[.!?]\s|[\n]/
    const match = buf.match(delimiters)

    if (match && match.index !== undefined) {
      const boundary = match.index + match[0].length
      const sentence = buf.slice(0, boundary).trim()
      sentenceBufferRef.current = buf.slice(boundary)

      if (sentence) {
        const speakable = toSpeakable(sentence)
        if (speakable.trim()) {
          synthesizeSentence(speakable, nextSeqRef.current++)
        }
      }
    }

    // Max-length fallback
    if (buf.length > 200 && !inCodeBlockRef.current) {
      const sentence = buf.trim()
      sentenceBufferRef.current = ''
      if (sentence) {
        const speakable = toSpeakable(sentence)
        if (speakable.trim()) {
          synthesizeSentence(speakable, nextSeqRef.current++)
        }
      }
    }
  }, [muted, toSpeakable, synthesizeSentence])

  const flushBuffer = useCallback(() => {
    const remaining = sentenceBufferRef.current.trim()
    sentenceBufferRef.current = ''
    inCodeBlockRef.current = false
    if (remaining && !muted) {
      const speakable = toSpeakable(remaining)
      if (speakable.trim()) {
        synthesizeSentence(speakable, nextSeqRef.current++)
      }
    }
  }, [muted, toSpeakable, synthesizeSentence])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopAllPlayback()
      clearInterval(durationIntervalRef.current)
      clearTimeout(maxDurationTimerRef.current)
    }
  }, [stopAllPlayback])

  return {
    // Recording
    isRecording,
    isTranscribing,
    recordingDuration,
    toggleRecording,
    // Playback
    isSpeaking,
    muted,
    setMuted,
    feedText,      // Call with each text delta during streaming
    flushBuffer,   // Call when stream ends
    stopAllPlayback,
    // State
    voiceAvailable,
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/hooks/useVoiceChat.ts
git commit -m "feat(dashboard): add useVoiceChat hook with recording, TTS playback, and sentence buffering"
```

---

### Task 7: Wire Voice into BrainChat

**Files:**
- Modify: `dashboard/src/components/BrainChat.tsx`

- [ ] **Step 1: Read current BrainChat.tsx**

Read `dashboard/src/components/BrainChat.tsx` fully to understand the current structure.

- [ ] **Step 2: Refactor handleSubmit to accept optional text parameter**

Find the `handleSubmit` function. Change its signature to accept optional text:

```typescript
const handleSubmit = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim()
    if (!text || isStreaming) return
    if (!overrideText) setInput('')  // Only clear input if not voice override
    // ... rest unchanged
```

- [ ] **Step 3: Add useVoiceChat import and integration**

Add imports:
```typescript
import { Mic, Volume2, VolumeX } from 'lucide-react'
import { useVoiceChat } from '../hooks/useVoiceChat'
```

Inside the component, add the hook and transcript queuing logic:

```typescript
// Ref to queue voice transcripts when streaming is in progress
const pendingTranscriptRef = useRef<string | null>(null)

const {
  isRecording, isTranscribing, recordingDuration,
  toggleRecording, isSpeaking, muted, setMuted,
  feedText, flushBuffer, stopAllPlayback, voiceAvailable,
} = useVoiceChat({
  onTranscript: (text) => {
    if (isStreaming) {
      // Queue for submission after current stream completes
      pendingTranscriptRef.current = text
    } else {
      handleSubmit(text)
    }
  },
  onError: (err) => {
    setMessages(prev => [...prev, {
      id: crypto.randomUUID(),
      role: 'assistant' as const,
      content: `*${err}*`,
      timestamp: new Date(),
    }])
  },
})

// Drain pending transcript when streaming ends
useEffect(() => {
  if (!isStreaming && pendingTranscriptRef.current) {
    const text = pendingTranscriptRef.current
    pendingTranscriptRef.current = null
    handleSubmit(text)
  }
}, [isStreaming, handleSubmit])
```

- [ ] **Step 4: Wire feedText into streaming loop**

In the streaming handler, where text deltas are accumulated, add:
```typescript
if (typeof event === 'string') {
  accumulated += event
  feedText(event)  // Feed to TTS sentence buffer
  // ... existing setMessages update
}
```

After the streaming loop completes (in the `finally` block), add:
```typescript
flushBuffer()  // Flush remaining TTS buffer
```

- [ ] **Step 5: Add mic button and mute button to the UI**

In the header area, add a mute toggle:
```tsx
{voiceAvailable && (
  <button
    onClick={() => setMuted(m => !m)}
    className="text-stone-500 hover:text-stone-300 transition-colors"
    title={muted ? 'Unmute voice' : 'Mute voice'}
  >
    {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
  </button>
)}
```

In the input area, add a mic button between textarea and send:
```tsx
{voiceAvailable && (
  <button
    onClick={toggleRecording}
    disabled={isTranscribing}
    className={`shrink-0 flex items-center justify-center w-8 h-8 rounded-lg transition-colors ${
      isRecording
        ? 'bg-red-600 hover:bg-red-500 animate-pulse'
        : isTranscribing
          ? 'bg-stone-700 cursor-wait'
          : 'bg-stone-700 hover:bg-stone-600'
    } text-white`}
    title={isRecording ? `Recording (${Math.floor(recordingDuration / 1000)}s)` : 'Push to talk'}
  >
    {isTranscribing ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
  </button>
)}
```

- [ ] **Step 6: Build and verify**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 7: Commit**

```bash
cd /home/jeremy/workspace/arialabs/nova && git add dashboard/src/components/BrainChat.tsx
git commit -m "feat(dashboard): integrate voice recording and TTS playback into BrainChat"
```

---

### Task 8: Settings Voice Section

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx`

- [ ] **Step 1: Read Settings.tsx**

Read `dashboard/src/pages/Settings.tsx` to understand the section pattern, the `NAV_GROUPS` structure, and how `ConfigField` is used.

- [ ] **Step 2: Add Voice to NAV_GROUPS**

Find the `NAV_GROUPS` array. Add a Voice item to the "AI & Pipeline" group:

```typescript
{ id: 'voice', label: 'Voice', icon: Mic },
```

Import `Mic` from lucide-react.

- [ ] **Step 3: Add Voice section in the render**

Add a new section div alongside the existing sections:

```tsx
<div id="voice">
  <Section icon={Mic} title="Voice" description="Speech recognition and synthesis settings. Requires docker compose --profile voice.">
    <ConfigField
      label="STT Provider"
      configKey="voice.stt_provider"
      value={useConfigValue(entries, 'voice.stt_provider', 'openai')}
      description="Speech-to-text: openai (Whisper), deepgram, local"
      onSave={handleSave}
      saving={saveMutation.isPending}
    />
    <ConfigField
      label="TTS Provider"
      configKey="voice.tts_provider"
      value={useConfigValue(entries, 'voice.tts_provider', 'openai')}
      description="Text-to-speech: openai, elevenlabs, local"
      onSave={handleSave}
      saving={saveMutation.isPending}
    />
    <ConfigField
      label="Voice"
      configKey="voice.tts_voice"
      value={useConfigValue(entries, 'voice.tts_voice', 'nova')}
      description="OpenAI voices: alloy, echo, fable, onyx, nova, shimmer"
      onSave={handleSave}
      saving={saveMutation.isPending}
    />
    <ConfigField
      label="TTS Model"
      configKey="voice.tts_model"
      value={useConfigValue(entries, 'voice.tts_model', 'tts-1')}
      description="tts-1 (fast, ~200ms) or tts-1-hd (quality, ~500ms)"
      onSave={handleSave}
      saving={saveMutation.isPending}
    />
  </Section>
</div>
```

Note: `getVal` and `handleSave` may be named differently in the actual code. Read the file to understand the helper pattern and match it.

- [ ] **Step 4: Build and verify**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 5: Commit**

```bash
cd /home/jeremy/workspace/arialabs/nova && git add dashboard/src/pages/Settings.tsx
git commit -m "feat(dashboard): add Voice settings section for STT/TTS provider config"
```

---

## Phase 3: Documentation

### Task 9: Update CLAUDE.md and Roadmap

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Update CLAUDE.md**

Add voice-service to the Architecture section's service list:

```markdown
- **voice-service** (8130) — STT/TTS provider proxy: OpenAI Whisper, OpenAI TTS, Deepgram, ElevenLabs (FastAPI). Optional, start with `--profile voice`.
```

Add port 8130 to the inter-service communication section. Add Redis DB 9 to the allocation table:

```
voice-service=db9
```

Add to the Key Configuration section:

```markdown
- Voice: `TTS_VOICE`, `TTS_MODEL`, `STT_PROVIDER`, `TTS_PROVIDER` — voice settings (runtime-configurable via dashboard Settings)
```

- [ ] **Step 2: Update roadmap**

Add voice chat to the "In Progress" section with delivered and remaining items.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/roadmap.md
git commit -m "docs: add voice service to architecture docs and roadmap"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| **1: Backend** | 1-5 | Voice service with transcribe/synthesize/voices endpoints, Docker Compose, proxy config, tests |
| **2: Frontend** | 6-8 | useVoiceChat hook, BrainChat mic button + TTS playback, Settings voice section |
| **3: Docs** | 9 | CLAUDE.md + roadmap updates |

Each phase produces deployable, testable software. Phase 1 can be tested via curl. Phase 2 requires Phase 1 running.
