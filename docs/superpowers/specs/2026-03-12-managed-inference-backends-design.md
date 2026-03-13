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

### New User Flow

1. Setup script runs hardware detection, stores results in Redis
2. Dashboard shows "Local Inference" section in Settings → AI & Models
3. User picks a backend (or Nova recommends one based on hardware)
4. Recovery service pulls the container image and starts it
5. LLM gateway auto-discovers models and starts routing

## Hardware Detection

Runs at two points:
1. **Setup time** — `setup.sh` does initial detection
2. **Runtime** — Recovery service re-checks on startup

Detects:
- GPU vendor (NVIDIA/AMD/none)
- GPU model and VRAM
- Available Docker runtime (`nvidia-container-toolkit`, ROCm)
- CPU cores, available RAM

Stored in Redis as `nova:system:hardware`:
```json
{
  "gpu_vendor": "nvidia",
  "gpu_model": "RTX 3060",
  "gpu_vram_gb": 12,
  "docker_gpu_runtime": "nvidia",
  "cpu_cores": 8,
  "ram_gb": 32,
  "detected_at": "2026-03-12T..."
}
```

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
- **Graceful switching** — stopping one backend and starting another drains in-flight requests first
- **Auto-restart** — if the inference container crashes, Recovery restarts it
- **Remote GPU support** — for split topologies, config points to a remote URL instead of managing a local container. WoL integration carries over.

### Container Details

- vLLM: `vllm/vllm-openai:latest`, `--model` flag set to user's selected model, GPU memory utilization configurable
- Ollama: `ollama/ollama`, same as today
- Images pulled lazily on first backend selection, not at install time

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

- New `LocalInferenceProvider` wraps the active backend. Gateway reads `nova:config:inference.backend` from Redis and delegates to the appropriate provider class.
- Fallback chain: `[LocalInferenceProvider] → [cloud chain]` instead of `[OllamaProvider] → [cloud chain]`
- If backend is "none", `LocalInferenceProvider.is_available` returns `False` and routing skips it

### New Provider Classes

| Class | Protocol | Notes |
|-------|----------|-------|
| `OpenAICompatibleProvider` | OpenAI `/v1/chat/completions`, `/v1/embeddings` | Base class for vLLM, SGLang, RemoteInference |
| `VLLMProvider` | Extends above | Thin — vLLM speaks native OpenAI format |
| `SGLangProvider` (Phase 3) | Extends above | Same protocol, different container |
| `RemoteInferenceProvider` (Phase 3) | Extends above | Custom URL + optional auth header |
| `OllamaProvider` | Existing | No changes |

### Discovery

- `_discover_vllm()` queries `GET /v1/models` on the running backend
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
- Download progress tracking (SSE from recovery service)

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
