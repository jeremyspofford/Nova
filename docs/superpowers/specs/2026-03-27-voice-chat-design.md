# Voice Chat for Nova

**Date:** 2026-03-27
**Status:** Approved
**Scope:** Voice service (STT + TTS), Brain page integration, push-to-talk v1

## Problem

Nova's Brain page creates an immersive visual experience — a full-viewport neural graph that pulses and glows as Nova thinks. But interaction is keyboard-only, which breaks immersion. Your eyes are on the graph; looking down to type disconnects you from the experience.

Voice input is the natural modality when attention is visual. Voice output completes the loop — talk to Nova, watch the graph respond, hear it answer. No other AI platform combines real-time knowledge graph visualization with voice conversation.

## Core Principle

**Voice is an enhancement, never a replacement.** Text chat always works. Voice adds a modality — it doesn't gate any functionality behind it. Deaf/hard-of-hearing users, noisy environments, and privacy-sensitive contexts all need text to remain first-class.

## Architecture

### Voice Service (New Microservice)

A thin proxy that abstracts STT and TTS providers behind a consistent API. It never touches the LLM layer — the existing `streamChat()` path handles all AI interaction.

```
Port: 8130
Redis: DB 9
Profile: voice (optional, --profile voice)
Depends on: redis
```

Two REST endpoints:

```
POST /api/v1/voice/transcribe    audio in → text out
POST /api/v1/voice/synthesize    text in → complete MP3 audio out
```

REST, not WebSocket, because v1 push-to-talk gives you a complete audio recording. WebSocket streaming gets added in v2 for always-listening mode.

### Data Flow

```
1. User holds mic button → browser records audio (WebM/Opus)
2. User releases → browser sends audio to voice service
3. Voice service → STT provider (Whisper) → transcript text
4. Voice service returns transcript to browser
5. Browser feeds transcript into BrainChat handleSubmit (existing path)
6. streamChat() → orchestrator → LLM → streaming response text
7. Browser buffers text into sentences
8. Per sentence: POST /synthesize → voice service → TTS provider → MP3
9. Browser queues and plays MP3 chunks sequentially
```

Steps 5-6 are the existing chat infrastructure, unchanged. The voice service only handles STT (steps 2-4) and TTS (steps 8-9).

### Why This Architecture

- **API keys stay server-side.** Browser never sees OpenAI/Deepgram keys.
- **Provider abstraction.** Same pattern as the LLM gateway — swap providers without touching the frontend.
- **Speaker ID ready.** The `/transcribe` response shape has room for `speaker_id` when v2 adds voiceprint matching.
- **Stateless.** No session management in the voice service — audio in, text out. Text in, audio out. Simple to scale, debug, and test.

## Providers

### STT (Speech-to-Text)

| Provider | Latency | Quality | Cost | Streaming | Speaker ID | Notes |
|---|---|---|---|---|---|---|
| **OpenAI Whisper** | 500-2000ms (batch) | Excellent | $0.006/min | No | No | Default — most users already have an OpenAI key |
| **Deepgram Nova-2** | 100-300ms (streaming) | Excellent | $0.0043/min | Yes | Yes (diarization) | Recommended upgrade for real-time + speaker ID |
| **faster-whisper** (local) | 200-1000ms (GPU) | Good-excellent | Free | No | No | Self-hosted, requires GPU for good performance |

**Default: OpenAI Whisper.** It's batch-only (not streaming), but for push-to-talk the full recording is available before transcription starts. Latency is acceptable (500-2000ms depending on audio length). Most Nova users already have `OPENAI_API_KEY` configured.

**Upgrade path: Deepgram.** When v2 adds always-listening mode, Deepgram's real-time streaming and built-in speaker diarization make it the clear choice.

### TTS (Text-to-Speech)

| Provider | First Audio | Quality | Cost | Voices | Notes |
|---|---|---|---|---|---|
| **OpenAI TTS** | ~200ms (tts-1) | Natural | $0.015/1K chars | 6 (alloy, echo, fable, onyx, nova, shimmer) | Default — fast, natural, same API key |
| **OpenAI TTS HD** | ~500ms (tts-1-hd) | Very natural | $0.030/1K chars | 6 | Quality option in Settings |
| **ElevenLabs** | ~300ms | Best | $0.18/1K chars | 1000+ | Future provider — voice cloning, custom voices |
| **Piper** (local) | ~100ms | Decent | Free | 100+ | Self-hosted, CPU-friendly, lower quality |

**Default: OpenAI `tts-1` with voice `nova`.** Fast (~200ms to first audio), natural quality, same API key as Whisper. The voice named "nova" is warm and clear — fitting for the platform.

**Model selection:** `tts-1` (fast) as default, `tts-1-hd` (quality) as user option in Settings. Speed wins for conversation — 300ms extra per sentence compounds and breaks the conversational feel.

### Provider Interface

```python
class STTProvider(ABC):
    async def transcribe(self, audio: bytes, format: str = "webm") -> TranscriptResult:
        """Transcribe audio to text. Format is the MIME subtype (webm, mp4, ogg, wav)."""
        """Transcribe audio to text. Returns transcript with metadata."""
        ...

class TTSProvider(ABC):
    async def synthesize(self, text: str, voice: str, model: str) -> bytes:
        """Convert text to audio. Returns MP3 bytes."""
        ...

@dataclass
class TranscriptResult:
    text: str
    language: str = "en"
    duration_ms: int = 0
    confidence: float = 0.0
    speaker_id: str | None = None  # v2: voiceprint match
```

Each provider implements these ABCs. The voice service routes to the configured provider. Adding a new provider is one file.

## Voice Service Implementation

### Configuration

```python
class Settings(BaseSettings):
    # Provider selection
    stt_provider: str = "openai"        # openai, deepgram, local
    tts_provider: str = "openai"        # openai, elevenlabs, local

    # Voice settings
    tts_voice: str = "nova"             # provider-specific voice ID
    tts_model: str = "tts-1"           # tts-1 (fast) or tts-1-hd (quality)

    # API keys (shared with LLM gateway)
    openai_api_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""

    # Auth (same pattern as all Nova services)
    require_auth: bool = True
    cors_allowed_origins: str = "http://localhost:3001,http://localhost:5173"

    # Limits
    max_audio_duration_seconds: int = 60
    max_tts_chars: int = 4096
    tts_rate_limit_per_minute: int = 120  # per user/API key, not global

    # Service
    redis_url: str = "redis://redis:6379/9"
    service_host: str = "0.0.0.0"
    service_port: int = 8130
    log_level: str = "INFO"
```

**Runtime-configurable via Redis** (`nova:config:voice.*`): provider, voice, model. Editable from dashboard Settings. `.env` values are boot defaults only.

### Endpoints

**`POST /api/v1/voice/transcribe`**

```
Request:
  Content-Type: multipart/form-data
  Body: audio file (WebM/Opus, max 25MB)

Response: 200
{
  "text": "What books have I read about AI?",
  "language": "en",
  "duration_ms": 3200,
  "confidence": 0.95,
  "speaker_id": null
}

Errors:
  400: Audio too long (> max_audio_duration_seconds)
  400: No audio provided
  422: Audio format not supported
  500: STT provider error (with retry info)
  503: STT provider not configured
```

**`POST /api/v1/voice/synthesize`**

```
Request:
  Content-Type: application/json
  Body: {"text": "Hello!", "voice": "nova", "model": "tts-1"}

Response: 200
  Content-Type: audio/mpeg
  Body: [complete MP3 binary — NOT chunked streaming, complete file per request]

Errors:
  400: Text too long (> max_tts_chars)
  400: Empty text
  429: Rate limit exceeded
  500: TTS provider error
  503: TTS provider not configured
```

**`GET /api/v1/voice/voices`**

```
Response: 200
{
  "provider": "openai",
  "voices": [
    {"id": "nova", "name": "Nova", "preview_url": null},
    {"id": "alloy", "name": "Alloy", "preview_url": null},
    ...
  ]
}
```

**`GET /health/live`** and **`GET /health/ready`**

Ready check verifies the configured STT and TTS providers are available. **Does NOT make real STT/TTS API calls** — that would cost money on every 15-second health check interval. Instead: validates API key format is present and non-empty, and optionally calls a lightweight metadata endpoint (e.g., OpenAI's `GET /v1/models` which is free). Returns provider availability so the dashboard knows whether to show the mic button.

```
{
  "status": "ready",
  "stt_provider": "openai",
  "stt_available": true,
  "tts_provider": "openai",
  "tts_available": true
}
```

### Rate Limiting

TTS requests are rate-limited per API key (authenticated) or per IP (dev mode):
- Default: 120 requests/minute per user (configurable)
- Redis sliding window (same pattern as LLM gateway)
- 429 response with `Retry-After` header
- **Self-imposed vs upstream:** A 429 from the voice service means the user exceeded their quota. A 502/503 from an upstream provider (OpenAI rate limit) is a different error — the voice service should distinguish these in the error response so the dashboard can show appropriate messaging.

### Authentication

Same pattern as all Nova services:
- `REQUIRE_AUTH` env var (default `false` for dev, should be `true` in production)
- When enabled: `X-Admin-Secret` header or `Authorization: Bearer sk-nova-<hash>` required on all endpoints
- Rate limiting applies per API key (authenticated) or per IP (unauthenticated dev mode)
- Without auth, anyone who can reach the voice service can proxy requests to paid STT/TTS APIs

### CORS

Add `CORSMiddleware` matching the pattern in every other Nova service:
- `cors_allowed_origins: str` setting in config
- Default: `"http://localhost:3001,http://localhost:5173"`

### Privacy

- **Audio is never persisted.** Processed in memory, discarded after transcription. No filesystem writes, no database storage.
- **Audio is never logged.** Not even at DEBUG level. Only metadata is logged (duration, language, confidence).
- **Transcripts are ephemeral.** The voice service returns the transcript and forgets it. Persistence happens downstream (the chat system stores messages, the engram system ingests knowledge — same as text chat).

### Cost Tracking

Each request records:
```python
{
    "type": "stt" | "tts",
    "provider": "openai",
    "duration_ms": 3200,        # STT: audio length
    "chars": 156,               # TTS: text length
    "estimated_cost_usd": 0.002,
    "timestamp": "ISO8601",
    "user_id": "uuid" | null
}
```

Stored in Redis with 7-day TTL for dashboard display. **Note:** Redis cost data is ephemeral — if Redis is flushed before `usage_events` table integration lands, cost history is lost. Future: persist to `usage_events` table alongside LLM costs for durable tracking.

## Dashboard Integration

### BrainChat Microphone Button

Add between the textarea and send button:

```
[  textarea input  ] [mic] [send]
```

**States:**
1. **Idle** — Mic icon (gray). Tap to start recording.
2. **Recording** — Mic icon (red, pulsing). Timer shows elapsed time. Waveform visualization in the input area. Tap again to stop and send.
3. **Transcribing** — Spinner replaces mic icon. "Transcribing..." text.
4. **Error** — Red flash, error message below input. Falls back to text input.

**Recording behavior:**
- Uses `MediaRecorder` API with runtime MIME type selection: try `audio/webm;codecs=opus` (Chrome/Firefox), fall back to `audio/mp4` (Safari/iOS), then `audio/ogg;codecs=opus`. Use `MediaRecorder.isTypeSupported()` to detect. Pass actual MIME type to `/transcribe` via the `format` field.
- Max duration: 60 seconds. Countdown appears after 45s. Auto-stops at 60s.
- On stop: send audio blob to voice service `/transcribe`
- On transcript received: call `handleSubmit(transcript)` directly. **Implementation note:** `handleSubmit` in BrainChat must be refactored to accept an optional `text?: string` parameter. When provided, use it instead of reading from `input` state. This avoids React state batching timing issues where `setInput(transcript)` + `handleSubmit()` would read the stale `input` value from the closure.
- If `isStreaming` is true when transcript arrives (user spoke while Nova was still responding): queue the transcript for submission after the current stream completes. Document this as a known v1 limitation — the voice input is queued, not dropped.

**Interruption handling (critical):**
When user presses mic while TTS audio is playing:
1. Immediately stop all TTS playback (pause + clear queue)
2. Clear the audio sentence queue
3. THEN start recording

Without this, Nova's voice gets picked up by the mic and transcribed as the user's input.

### Audio Playback

**Sentence buffering** — As the LLM streams text, JavaScript buffers until a sentence boundary:
- Primary delimiters: `. `, `? `, `! `, `\n`
- Skip delimiters inside backtick blocks (code)
- Max-length fallback: 200 characters (don't wait forever for a period)
- **Stream end:** when the LLM stream completes, unconditionally flush whatever remains in the buffer as a final TTS request, regardless of length or delimiter presence
- Strip markdown before sending to TTS (`#`, `**`, `` ` ``, `- ` list markers)

**Playback queue** — Sentences are synthesized in parallel (up to 3 concurrent) but played in sequence:
```
Sentence 1: synthesizing... [playing ▶]
Sentence 2: synthesizing... [queued]
Sentence 3: [buffering text...]
```
Each sentence gets a sequence number. Playback only advances when the next-in-sequence audio is ready. If sentence 3 finishes before sentence 2, it waits.

**Audio output:**
- Create `Audio` element per sentence from MP3 blob URL
- On `ended` event: play next in queue
- No visible player controls — responses just speak
- Small speaker icon on message bubbles that were spoken
- Mute button in BrainChat header silences TTS without disabling it (messages still stream as text)

### Settings Page — Voice Section

New section in the dashboard Settings page:

| Setting | Control | Redis Key |
|---|---|---|
| STT Provider | Dropdown (OpenAI / Deepgram / Local) | `nova:config:voice.stt_provider` |
| TTS Provider | Dropdown (OpenAI / ElevenLabs / Local) | `nova:config:voice.tts_provider` |
| Voice | Dropdown (fetched from `/voices`) + preview button | `nova:config:voice.tts_voice` |
| TTS Model | Toggle (Fast / HD) | `nova:config:voice.tts_model` |

Preview button plays a short sample: "Hello, I'm Nova." in the selected voice.

### Provider Availability Gating

The mic button only appears when:
1. The voice service is running (`--profile voice`)
2. `/health/ready` reports `stt_available: true`

If the voice service isn't running, no mic button. If it's running but the provider has no API key, show a disabled mic with tooltip: "Voice requires an OpenAI API key — configure in Settings."

The dashboard checks voice service health on mount (alongside other service health checks in the startup screen).

### Mic Permission Handling

Browser mic access requires user permission. On first mic button press:
- Browser shows native permission prompt
- If denied: show tooltip "Microphone access denied. Enable in browser settings."
- If granted: proceed with recording
- Permission state cached — subsequent presses skip the prompt

## Error Handling

| Scenario | User Experience | Technical |
|---|---|---|
| STT fails (timeout/500) | "Transcription failed — try again or type your message" | 1 retry with 500ms delay, then show error |
| STT returns empty text | "Couldn't understand that — try again" | Don't submit empty string |
| TTS fails for a sentence | Skip that sentence, continue playing next | Log warning, don't interrupt playback |
| TTS rate limited (429) | Fall back to text-only for remaining sentences | Respect `Retry-After`, resume TTS after cooldown |
| Voice service unreachable | Mic button disappears | Health check polling (30s interval) |
| Mic permission denied | Tooltip explaining how to enable | `navigator.permissions.query({name: 'microphone'})` |
| Recording too long (60s) | Countdown at 45s, auto-stop at 60s | `setTimeout` on `MediaRecorder.start()` |
| Provider API key missing | Disabled mic with tooltip | `/health/ready` reports `stt_available: false` |

## Future: Speaker Identification (v2)

Not in v1, but the architecture supports it:

**Enrollment:**
- Each user records a 15-30 second voice sample via a Settings UI
- Voice service extracts a 256-dim speaker embedding (speechbrain or resemblyzer, both open-source, run locally)
- Embedding stored in user profile (small vector, ~1KB)
- Enrollment audio discarded after embedding extraction

**Recognition:**
- On each `/transcribe` call, extract embedding from incoming audio
- Compare against enrolled embeddings via cosine similarity
- Match (>0.85 threshold) → populate `speaker_id` in response
- No match → `speaker_id: null` (guest)

**Integration with RBAC:**
- Voice-identified user gets their role's permissions automatically
- Unknown voices default to Guest (no tools, no memory, filtered model access — already implemented)
- Multiple users in the same room: diarization (Deepgram) separates speakers before identification

**Home assistant context:**
- Wake word detection (v3) — "Hey Nova" activates listening
- Continuous listening with VAD (v3) — detects speech vs silence vs background noise
- Smart stop — Nova knows when it's being addressed vs overhearing conversation

## Files

### New Files

| File | Responsibility |
|---|---|
| `voice-service/app/main.py` | FastAPI app, health endpoints, CORS |
| `voice-service/app/config.py` | Pydantic settings |
| `voice-service/app/routes.py` | `/transcribe`, `/synthesize`, `/voices` endpoints |
| `voice-service/app/providers/__init__.py` | Provider registry |
| `voice-service/app/providers/openai_stt.py` | OpenAI Whisper STT |
| `voice-service/app/providers/openai_tts.py` | OpenAI TTS |
| `voice-service/app/providers/deepgram_stt.py` | Deepgram STT (optional) |
| `voice-service/app/providers/elevenlabs_tts.py` | ElevenLabs TTS (optional) |
| `voice-service/Dockerfile` | Python 3.12-slim container |
| `voice-service/pyproject.toml` | Dependencies |
| `dashboard/src/hooks/useVoiceChat.ts` | MediaRecorder + audio playback hook |
| `tests/test_voice.py` | Integration tests |

### Modified Files

| File | Change |
|---|---|
| `docker-compose.yml` | Add voice-service with profile `voice`, develop.watch block |
| `.env.example` | Add `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, voice settings |
| `dashboard/src/components/BrainChat.tsx` | Add mic button, refactor `handleSubmit` to accept optional text param, wire useVoiceChat hook |
| `dashboard/src/pages/settings/SettingsPage.tsx` | Add Voice section |
| `dashboard/vite.config.ts` | Add `/voice` proxy to localhost:8130 |
| `dashboard/nginx.conf` | Add `/voice-api/` location block for production proxy to voice-service:8130 |
| `CLAUDE.md` | Document voice service, add port 8130 + Redis DB 9 to allocation tables |
| `docs/roadmap.md` | Add voice chat to roadmap |

**Scoped out of v1 (listed as providers but not in the files list):**
- `local_stt.py` (faster-whisper) and `local_tts.py` (Piper) — self-hosted providers require GPU infrastructure and additional Docker Compose profiles. Deferred to v2 alongside always-listening mode.

## Dependencies

- `openai>=1.0` — Whisper API + TTS API (already in the ecosystem)
- `httpx` — async HTTP client for provider calls (already used everywhere)
- `python-multipart` — for `multipart/form-data` audio upload in FastAPI

No new infrastructure. Voice service is a FastAPI app like every other Nova service.

## Testing

**Integration tests (`tests/test_voice.py`):**
- Health endpoints (live, ready)
- Transcribe with a pre-recorded WAV/WebM fixture file
- Synthesize returns valid MP3 audio
- Rate limiting returns 429
- Missing API key returns 503
- Audio too long returns 400

**Dashboard testing:**
- Mic button appears when voice service is healthy
- Mic button hidden when voice service is down
- Recording starts/stops on button press
- Transcript appears in chat input
- Audio plays sequentially after response
- Interruption: pressing mic stops playback
- Mute button silences TTS
