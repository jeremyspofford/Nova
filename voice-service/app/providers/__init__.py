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
