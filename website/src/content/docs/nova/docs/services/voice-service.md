---
title: "Voice Service"
description: "Speech recognition and text-to-speech proxy. Port 8130. Optional, requires voice profile."
---

The Voice Service provides speech-to-text (STT) and text-to-speech (TTS) capabilities for Nova. It acts as a provider proxy, routing requests to configurable backends (OpenAI Whisper, Deepgram, ElevenLabs) with runtime-switchable configuration.

## At a glance

| Property | Value |
|----------|-------|
| **Port** | 8130 |
| **Framework** | FastAPI |
| **State store** | Redis (db 9) |
| **Source** | `voice-service/` |
| **Profile** | `voice` (opt-in: `docker compose --profile voice up`) |

## Key responsibilities

- **Speech-to-text** -- transcribe audio files (WebM, MP4, OGG, WAV, MPEG, M4A) up to 25MB via configurable STT provider
- **Text-to-speech** -- synthesize text to MP3 audio via configurable TTS provider
- **Provider abstraction** -- swap STT/TTS providers at runtime without code changes
- **Runtime configuration** -- API keys, provider selection, voice, and model settings update live via Redis without restart
- **Health reporting** -- exposes provider availability so the dashboard can show/hide voice UI

## API endpoints

### Transcribe (STT)

```
POST /api/v1/voice/transcribe

Content-Type: multipart/form-data
  file: <audio blob>
  format: webm | mp4 | ogg | wav | mpeg | m4a
  language: en  (optional)

Response:
{
  "text": "transcribed text",
  "language": "en",
  "duration_ms": 3200,
  "confidence": 0.95,
  "speaker_id": null
}
```

Silence guard: if `confidence < 0.4` and `duration < 1000ms`, returns empty text to avoid hallucination on silence.

### Synthesize (TTS)

```
POST /api/v1/voice/synthesize

Content-Type: application/json
{
  "text": "Hello world",
  "voice": "nova",
  "model": "tts-1"
}

Response:
Content-Type: audio/mpeg
Body: MP3 audio bytes
```

Available voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`.

### List voices

```
GET /api/v1/voice/voices

Response:
[{ "id": "nova", "name": "Nova", "provider": "openai" }, ...]
```

## Providers

| Provider | STT | TTS | Notes |
|----------|-----|-----|-------|
| **OpenAI** | Whisper-1 | TTS-1 / TTS-1-HD | Default. Requires `OPENAI_API_KEY`. |
| **Deepgram** | Nova-2 | -- | Fast streaming. Requires `DEEPGRAM_API_KEY`. |
| **ElevenLabs** | -- | Various | High quality voices. Requires `ELEVENLABS_API_KEY`. |

Provider resolution order:
1. Redis config (`nova:config:voice.stt_provider`)
2. Environment variable (`STT_PROVIDER`)
3. Default: `openai`

## Dashboard integration

### Voice chat

The dashboard integrates voice in two places:

- **Chat page (`/chat`)** -- Voice input via browser Web Speech API (free, no backend needed). The InputDrawer has a mic button with live transcription display.
- **Brain page (`/brain`)** -- Full voice pipeline via the voice service. MediaRecorder captures audio, Whisper transcribes, and TTS reads responses aloud sentence-by-sentence as they stream in.

### Conversation mode

The Brain page supports a **conversation mode** for hands-free, Gemini-style voice interaction:

1. Click the waveform toggle button to enter conversation mode
2. Speak naturally -- Nova auto-detects when you stop talking and submits
3. Nova responds with streaming TTS
4. **Barge-in**: start talking while Nova is speaking to interrupt her immediately
5. When Nova finishes speaking, she auto-listens for your next input
6. Press Escape or click the toggle to exit

**How it works:**

- **Warm mic** -- a single persistent `getUserMedia` stream stays alive for the whole conversation, eliminating the 200ms+ latency of reconnecting the mic between turns
- **Barge-in detection** -- an `AnalyserNode` monitors audio levels during TTS playback; sustained voice above the threshold triggers an interrupt
- **Silence detection** -- when audio level drops below threshold for the configured timeout, recording auto-stops and submits
- **Auto-exit** -- 3 consecutive silent or failed turns automatically exits conversation mode

### Settings

Voice settings are in Dashboard > Settings > Voice:

| Setting | Storage | Description |
|---------|---------|-------------|
| OpenAI API Key | Redis | Key for Whisper + TTS |
| STT Provider | Redis | `openai`, `deepgram` |
| TTS Provider | Redis | `openai`, `elevenlabs` |
| Voice | Redis | TTS voice selection |
| TTS Model | Redis | `tts-1` (fast) or `tts-1-hd` (quality) |
| Silence Timeout | localStorage | How long to wait after you stop talking (default 2000ms) |
| Barge-in Threshold | localStorage | Audio level to trigger interruption (default 0.15) |

## Configuration

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STT_PROVIDER` | Speech-to-text provider | `openai` |
| `TTS_PROVIDER` | Text-to-speech provider | `openai` |
| `TTS_VOICE` | Default TTS voice | `nova` |
| `TTS_MODEL` | TTS model | `tts-1` |
| `OPENAI_API_KEY` | Required for OpenAI Whisper/TTS | *(shared with LLM provider)* |
| `DEEPGRAM_API_KEY` | Required for Deepgram STT | *(optional)* |
| `ELEVENLABS_API_KEY` | Required for ElevenLabs TTS | *(optional)* |

### Runtime configuration (Redis)

All voice settings are runtime-configurable via the dashboard. Changes take effect immediately.

| Redis Key | Values |
|-----------|--------|
| `nova:config:voice.stt_provider` | `openai`, `deepgram` |
| `nova:config:voice.tts_provider` | `openai`, `elevenlabs` |
| `nova:config:voice.tts_voice` | `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer` |
| `nova:config:voice.tts_model` | `tts-1`, `tts-1-hd` |
| `nova:config:voice.openai_api_key` | API key override |

## Health endpoints

```
GET /health/live   → { "status": "alive" }
GET /health/ready  → {
  "status": "ready" | "degraded",
  "stt_provider": "openai",
  "stt_available": true,
  "tts_provider": "openai",
  "tts_available": true
}
```

The dashboard polls `/health/ready` every 30 seconds. Voice UI elements are hidden when the service is unavailable.
