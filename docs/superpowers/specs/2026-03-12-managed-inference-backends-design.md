# Managed Inference Backends

**Date:** 2026-03-12
**Status:** Approved

## Problem

Nova currently only supports Ollama for local inference. Ollama is beginner-friendly but not optimized for production throughput. Users need choice of inference backends based on their hardware and performance requirements, and Nova should manage the backend lifecycle so it "just works."

## Goals

- Give users a performant local inference option that works out of the box
- Support all deployment topologies: single machine (GPU or not), split topology (always-on host + remote GPU), cloud GPU instances
- Everything configurable from the dashboard UI — no .env editing for runtime settings
- Local AI is the primary feature; cloud LLMs remain fully supported as an option
- Each phase delivers standalone value

## Non-Goals

- LMStudio integration (desktop GUI app, not suited for headless/Docker; users can connect it as a custom OpenAI-compatible endpoint)
- Canonical model name mapping across backends (tier resolver already handles routing regardless of backend-specific names)

## Supported Backends

| Backend | Role | When to use | Managed by Nova? |
|---------|------|-------------|-----------------|
| **vLLM** | Production GPU inference | NVIDIA/AMD GPU available, throughput matters | Yes |
| **SGLang** | Pipeline-optimized GPU inference (Phase 3) | RadixAttention benefits for shared-prefix pipelines | Yes |
| **Ollama** | Easy mode / CPU fallback | No GPU, beginners, casual use | Yes |
| **Cloud providers** | Remote inference | No local hardware, or as fallback | Configured via API keys in UI |
| **Custom endpoint** | Bring-your-own | User runs their own server elsewhere | User provides URL |

### Recommended Backend Logic

- NVIDIA GPU + >=8GB VRAM → recommend **vLLM**
- AMD GPU (ROCm) → recommend **vLLM** (ROCm build)
- CPU only → recommend **Ollama**
- No local hardware → recommend **Cloud providers**

## Architecture

### Component Placement

```
Dashboard Settings UI
        │
        ▼
   Orchestrator API  ←── stores config in Redis
        │
        ▼
   LLM Gateway  ←── reads config, routes to backends
        │
        ▼
   Recovery Service (Inference Manager)
     ├── Hardware Detector — detects GPU, VRAM, CPU at startup
     ├── Backend Controller — starts/stops inference containers via Docker SDK
     └── Model Manager — downloads, lists, deletes models per backend
```

No new services. The Inference Manager is a module inside the recovery service, which already has Docker SDK access.

### Where Things Live

- **Recovery service** — inference container lifecycle (start/stop/health), hardware detection, model downloads
- **LLM gateway** — provider classes (VLLMProvider, SGLangProvider), routing, discovery
- **Dashboard** — Settings UI for backend selection, Model Library page
- **Redis** — all inference config (`nova:config:inference.*`)

### Redis Access

Recovery service needs Redis access (currently connects only to Postgres). Add `REDIS_URL` to its environment in docker-compose, using **db6** (next available: orchestrator=db2, llm-gateway=db1, chat-api=db3, memory-service=db0, chat-bridge=db4, cortex=db5).

Hardware detection results go to `nova:system:hardware` on db6 — a new `nova:system:*` namespace for read-only system facts (distinct from `nova:config:*` which is read-write user config). The LLM gateway reads inference config from its own db1 via the existing `nova:config:inference.*` keys, written by the orchestrator's config sync. Recovery reads `nova:config:inference.backend` cross-db from db1 to know which container to manage.

### Communication Paths

Two paths, matching existing patterns:

1. **Config changes** (which backend, model preferences): Dashboard → Orchestrator API (`platform_config`) → Redis sync → LLM Gateway reads. Same pattern as LLM routing strategy.
2. **Lifecycle actions** (start/stop container, pull image, model download): Dashboard → Recovery service directly. Same pattern as existing compose profile management at `POST /api/v1/recovery/services/{name}/restart`.

### New User Flow

1. Setup script runs hardware detection, writes to `data/hardware.json`
2. Services start — recovery reads `hardware.json`, syncs to Redis (`nova:system:hardware`)
3. Dashboard shows "Local Inference" section in Settings → AI & Models with recommendation
4. User picks a backend (or accepts recommendation)
5. Dashboard calls recovery to pull image and start container
6. LLM gateway auto-discovers models and starts routing

## Hardware Detection

Runs at two points:
1. **Setup time** — `setup.sh` does initial detection
2. **Runtime** — Recovery service re-checks on startup

Detects:
- GPU vendor (NVIDIA/AMD/none)
- GPU model and VRAM
- Available Docker runtime (`nvidia-container-toolkit`, ROCm)
- CPU cores, available RAM

Stored in Redis as `nova:system:hardware` (on db6 — `nova:system:*` is a read-only namespace for system facts, distinct from `nova:config:*` for user settings):
```json
{
  "gpus": [
    {
      "vendor": "nvidia",
      "model": "RTX 3060",
      "vram_gb": 12,
      "index": 0
    }
  ],
  "docker_gpu_runtime": "nvidia",
  "cpu_cores": 8,
  "ram_gb": 32,
  "disk_free_gb": 120,
  "detected_at": "2026-03-12T..."
}
```

GPUs are an array to support multi-GPU setups. `disk_free_gb` is checked before model downloads — the UI warns if a model won't fit on disk (in addition to VRAM checks).

**Setup script vs. recovery:** `setup.sh` runs hardware detection before containers are up (no Redis). It writes results to `data/hardware.json`. Recovery reads this file on startup and syncs to Redis. Subsequent runtime re-detections update Redis directly.

## Backend Lifecycle

Managed by Recovery service via Docker SDK.

```
User selects backend in UI
        │
        ▼
  Recovery: pull container image (if needed)
        │
        ▼
  Recovery: start container with correct GPU flags
        │
        ▼
  LLM Gateway: health check loop detects new backend
        │
        ▼
  LLM Gateway: auto-discovers models, updates registry
        │
        ▼
  Ready to route
```

### Constraints

- **One local backend at a time** — running vLLM and Ollama simultaneously wastes GPU memory. User picks one, Nova manages it. (Custom endpoints are separate and can coexist.)
- **Graceful switching** — see Backend Switching Protocol below
- **Auto-restart** — inference containers use Docker's `restart: unless-stopped` policy. Recovery service runs a background health check every 30s against the inference container. After 3 consecutive failures, it force-recreates the container. Uses exponential backoff (30s, 60s, 120s) to avoid restart loops on persistent failures. The UI shows the error state.
- **Remote GPU support** — for split topologies, config points to a remote URL instead of managing a local container. WoL integration carries over.

### Backend Switching Protocol

When a user switches backends (e.g., Ollama → vLLM):

1. Recovery sets `nova:config:inference.state` = `draining` in Redis
2. LLM gateway sees `draining` state on next config read (5s cache), stops routing new requests to local backend. New requests fall back to cloud (if available) or return 503.
3. Recovery waits up to **15 seconds** for in-flight requests to complete (polls gateway's active request count via `GET /health/ready` which already tracks this)
4. After drain (or timeout), recovery stops the old container
5. Recovery pulls new image (if needed) and starts new container
6. Recovery sets `nova:config:inference.state` = `starting`
7. Gateway health check detects new backend, discovery runs
8. Recovery sets `nova:config:inference.state` = `ready`
9. Gateway resumes routing to local backend

If the new backend fails to start within 60s, state is set to `error` with a message. Cloud fallback continues to serve requests. UI shows the error.

### Container Management

Inference containers are defined as **Docker Compose services with profiles** (not raw Docker SDK). This ensures they join the Nova network, get proper naming, and are manageable by the existing `compose_client.py`.

Added to `docker-compose.yml`:
- `nova-vllm` service with `profiles: ["local-vllm"]`
- `nova-sglang` service (Phase 3) with `profiles: ["local-sglang"]`
- Existing `ollama` service unchanged

Recovery uses `compose_client.py` to start/stop profiled services — same mechanism used for existing service management.

### Container Details

- vLLM: `vllm/vllm-openai:v0.8.x` (pinned version, user-overridable in UI), `--model` flag set to user's selected model, GPU memory utilization configurable. Volume: `nova-vllm-cache` mounted to `/root/.cache/huggingface`
- Ollama: `ollama/ollama`, same as today. Volume: existing `ollama-data`
- Images pulled lazily on first backend selection, not at install time. **Requires internet access** for initial pull and model downloads.
- Container names follow convention: `nova-vllm`, `nova-sglang`, `nova-ollama`

## Model Management

Models are managed per-backend. No canonical name mapping — each backend uses its own naming (Ollama short names, vLLM uses HuggingFace repo IDs). The tier resolver handles routing regardless of name format.

### Model Library (Phase 2 — Dashboard Page)

New "Models" page in dashboard sidebar:
- Shows models from active backend's discovery endpoint
- States: "Loaded" (in GPU memory), "Cached" (downloaded, not loaded)
- Download with search against backend's catalog (HuggingFace for vLLM, Ollama registry for Ollama)
- VRAM-aware filtering — shows size estimates, warns if model won't fit
- Embedding model selector (separate from chat models, affects memory-service)
- Cloud Models section — read-only, shows available models based on configured API keys

### Storage

Models from different backends live in separate Docker volumes (Ollama has its own format, vLLM uses HuggingFace cache). Switching backends doesn't delete the other backend's models.

## Routing Integration

### Strategy System

Current routing strategies stay unchanged: `local-first`, `cloud-first`, `local-only`, `cloud-only`. What changes is what "local" means.

**Today:** "local" = Ollama at a hardcoded URL
**After:** "local" = whatever managed backend is active

### Implementation

- New `LocalInferenceProvider` wraps the active backend. Gateway reads `nova:config:inference.backend` and `nova:config:inference.state` from Redis (5s cache) and delegates to the appropriate provider class.
- Provider instance is **recreated** when the backend config changes (not hot-swapped mid-request). The gateway's config cache refresh (every 5s) checks for backend changes and instantiates the new provider. Requests already in-flight on the old provider complete normally against the old instance.
- Fallback chain: `[LocalInferenceProvider] → [cloud chain]` instead of `[OllamaProvider] → [cloud chain]`
- If backend is "none" or state is "draining"/"starting"/"error", `LocalInferenceProvider.is_available` returns `False` and routing skips it, falling through to cloud
- **Local model detection:** The existing `_is_ollama_model()` hardcoded set is replaced. `LocalInferenceProvider` maintains a set of models discovered from the active backend (populated by the discovery endpoint). Any model in that set is treated as "local" for routing strategy purposes. This set refreshes on discovery runs (triggered by backend changes and periodically).

### New Provider Classes

| Class | Protocol | Notes |
|-------|----------|-------|
| `OpenAICompatibleProvider` | OpenAI `/v1/chat/completions`, `/v1/embeddings` | Base class for vLLM, SGLang, RemoteInference |
| `VLLMProvider` | Extends above | Thin — vLLM speaks native OpenAI format |
| `SGLangProvider` (Phase 3) | Extends above | Same protocol, different container |
| `RemoteInferenceProvider` (Phase 3) | Extends above | Custom URL + optional auth header |
| `OllamaProvider` | Existing | No changes |

### Discovery

- `_discover_vllm()` queries `GET /v1/models` on the running backend. The backend URL is determined by Docker Compose service name (e.g., `http://nova-vllm:8000` for vLLM, `http://ollama:11434` for Ollama). The URL is stored in `nova:config:inference.url` so it can be overridden for remote backends.
- Catalog search (for download UI) queries HuggingFace API
- Ollama discovery unchanged

### Transparent Behavior

- Switching backends in UI automatically updates the routing chain
- Tier resolver re-resolves against newly available models
- In-flight requests complete before old backend shuts down
- If new backend fails to start, routing falls back to cloud (if configured) and UI shows error

## UI Design

### Settings → AI & Models → Local Inference Section

New section at top of AI & Models tab. Existing sections (LLM Routing, Provider Status, Context Budgets) remain below.

Contents:
- **Backend selector** — dropdown: vLLM, SGLang (Phase 3), Ollama, None
- **Recommendation** — based on detected hardware (e.g., "Recommended for your NVIDIA RTX 3060 (12GB VRAM)")
- **Status** — running/stopped/pulling/error, image version, GPU memory usage
- **Remote Backend toggle** — when enabled, hides local container controls, shows URL + WoL options
- **No GPU guidance** — if no GPU detected and no remote configured, steers toward cloud providers or remote backend setup

### Models Page (Phase 2)

New dashboard sidebar item. Shows:
- Local models with status (Loaded/Cached), size
- VRAM usage bar
- Download with catalog search and VRAM filtering
- Embedding model selector
- Cloud models summary (links to Settings for API key config)

### What Stays in .env

Only bootstrap/security config:
- `POSTGRES_PASSWORD`, `ADMIN_SECRET`, `NOVA_WORKSPACE`
- `DEFAULT_CHAT_MODEL` — initial default, overridden by UI after first use
- API keys — also settable in UI via Provider Status, `.env` is fallback for headless deploys

All inference backend config is UI-configured, stored in Redis.

## Phasing

### Phase 1 — vLLM Provider + Hardware Detection

Establishes the architecture. Delivers: users can run vLLM as a managed backend with GPU auto-detection.

- `OpenAICompatibleProvider` base class
- `VLLMProvider` class
- Hardware detection module in recovery service
- Backend lifecycle in recovery service (pull, start/stop, health)
- `LocalInferenceProvider` wrapper in gateway routing
- Settings UI: Local Inference section
- Model discovery for vLLM
- Update `setup.sh` for hardware detection

### Phase 2 — Model Library UI

- New "Models" page in dashboard
- Model catalog search (HuggingFace API for vLLM, Ollama registry for Ollama)
- VRAM-aware filtering and size estimates
- Embedding model selection
- Download progress tracking via SSE at `GET /api/v1/recovery/inference/models/download/{model_id}/progress`. Per-model stream with events: `{"status": "downloading", "progress_pct": 45, "downloaded_gb": 3.6, "total_gb": 8.0}`. Uses HuggingFace hub's progress callbacks for vLLM, Ollama's existing pull stream for Ollama.

### Phase 3 — SGLang + Remote Inference

- `SGLangProvider` (extends `OpenAICompatibleProvider`)
- `RemoteInferenceProvider` (custom URL + optional auth)
- WoL integration moved into inference manager
- Docker Compose profile for SGLang

### Phase 4 — Polish & Intelligence

- Auto-recommend backend based on hardware + workload
- Model recommendations based on VRAM and use case
- GPU memory monitoring in dashboard (live)
- Inference performance metrics (tokens/sec, latency) in UI
