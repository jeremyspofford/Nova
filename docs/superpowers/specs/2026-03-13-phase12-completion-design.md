# Phase 12 Completion — Model Library, SGLang, Custom Endpoints & Intelligence

**Date:** 2026-03-13
**Status:** Draft
**Builds on:** `2026-03-12-managed-inference-backends-design.md` (Phase 12a, complete)

## Problem

Phase 12a established the managed inference architecture (hardware detection, `OpenAICompatibleProvider`, `VLLMProvider`, `LocalInferenceProvider`, drain protocol, recovery lifecycle API, dashboard Local Inference section). What remains:

- The Models page doesn't adapt to the active backend — it's Ollama-only
- vLLM users can't switch models without manually restarting the container
- No onboarding experience for first-time users
- SGLang not yet supported
- Users with their own inference servers (llama.cpp, LMStudio, TGI) can't connect them
- No GPU monitoring or performance metrics
- No intelligent recommendations

## Goals

- Backend-aware Models page that adapts to Ollama vs vLLM vs SGLang
- vLLM model switching that feels as easy as Ollama (drain, restart, reload)
- First-visit onboarding wizard so new users can start chatting in minutes
- SGLang as a third managed backend
- Custom endpoint support for user-managed inference servers
- GPU monitoring and inference performance metrics in the dashboard
- Intelligent backend and model recommendations based on detected hardware

## Non-Goals

- Multi-model serving (vLLM/SGLang serve one model at a time)
- Automatic background model downloading (user-initiated only)
- Model fine-tuning UI
- CLI-based onboarding wizard (dashboard-only)

## Architecture

All three phases reuse the 12a infrastructure. No new services.

**Data flow for model operations:**
```
Dashboard → Recovery Service (lifecycle, model switch, GPU stats)
Dashboard → LLM Gateway (model discovery via /v1/models, inference stats)
Dashboard → Recovery Service (HuggingFace/Ollama model catalog search)
Dashboard → Orchestrator (platform_config for preferences, model history)
```

**New endpoints summary:**

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Recovery | `POST /inference/backend/{backend}/switch-model` | Drain + restart with new model |
| Recovery | `GET /inference/backend/status/stream` | SSE progress during model switch/download |
| Recovery | `GET /inference/models/search` | Proxy to HuggingFace/Ollama registry with VRAM filtering |
| Recovery | `GET /hardware/gpu-stats` | Live GPU utilization, VRAM, temperature |
| Recovery | `GET /inference/recommendation` | Auto-recommend backend + model |
| Gateway | `GET /v1/inference/stats` | Rolling performance metrics (tokens/sec, TTFT) |

**Design decision:** Model search lives in recovery (not gateway) because it's a catalog/lifecycle operation alongside backend management, not an inference routing operation. This keeps the gateway focused on inference.

---

## Phase 12b — Backend-Aware Models Page + Onboarding

### Backend-Aware Models Page

The Local Models section of `Models.tsx` renders different UIs based on the active backend from `GET /api/v1/recovery/inference/backend`.

**When Ollama is active:**
- Pulled models list with delete buttons (existing)
- Pull new model input (existing)
- Recommended models grid with category and size filters (new)

**When vLLM is active:**
- Active model card: model name, status (serving/loading/switching), VRAM usage
- "Switch Model" section:
  - Recently used models list (from `platform_config`)
  - HuggingFace search input
  - Each result shows model name, size estimate, "Load" button
  - Cached models get a badge (already downloaded, faster to load)

**When SGLang is active (Phase 12c):**
- Same UX as vLLM (both are single-model servers with HuggingFace models)

**When Custom is active (Phase 12c):**
- Shows discovered models from `GET /v1/models` on the custom endpoint
- Read-only — no download/switch controls

**When None:**
- Empty state with link to Settings to configure a backend

**Cloud Providers section** (bottom of page) remains unchanged.

### vLLM Model Switching

Users can switch vLLM's active model from the Models page. Reuses the 12a drain protocol.

**Flow:**
1. User clicks "Load" on a model → confirmation dialog: "Switching models restarts vLLM (~30-120s). Cloud providers remain available during the switch."
2. Dashboard calls `POST /api/v1/recovery/inference/backend/vllm/switch-model` with `{ "model": "org/model-name" }`
3. Recovery runs drain protocol in a background task:
   - Set `inference.state` = `draining`
   - Poll `GET /health/inflight` on gateway until 0 or 15s timeout
   - Stop vLLM container via `stop_profiled_service("local-vllm", "nova-vllm")`
   - Update `VLLM_MODEL` in `.env` via `patch_env()` (add `VLLM_MODEL` to `ENV_WHITELIST` in `env_manager.py`)
   - Start vLLM container via `start_profiled_service("local-vllm", "nova-vllm")` — compose reads updated `.env`
   - Wait for healthy (up to 120s for large model downloads)
   - Set `inference.state` = `ready`
4. Dashboard polls status via `GET /inference/backend` (TanStack Query `refetchInterval: 2000` during switch) for progress
5. UI shows step-by-step progress: Draining → Stopping → Downloading → Loading → Ready

**Env var update mechanism:** `VLLM_MODEL` and `SGLANG_MODEL` are added to `ENV_WHITELIST` in `recovery-service/app/env_manager.py`. The `switch_model()` method calls `patch_env({"VLLM_MODEL": new_model})` before restarting the container. Since `docker compose up` reads from `.env`, the new model is picked up on restart.

**Recovery endpoint:**
```python
# In recovery-service/app/inference/routes.py
@router.post("/api/v1/recovery/inference/backend/{backend}/switch-model")
async def switch_model(backend: str, body: SwitchModelRequest):
    # body.model: str — HuggingFace model ID (vLLM/SGLang) or Ollama tag
    # Validates backend supports model switching (vllm, sglang — not ollama/custom)
    # Runs drain + restart in background asyncio task
    # Returns 202 Accepted
```

**Progress tracking:** Rather than a separate SSE endpoint (which has auth complications — `EventSource` API cannot send `X-Admin-Secret` headers), the dashboard uses polling. TanStack Query polls `GET /inference/backend` every 2s during a switch, and the response includes a `switch_progress` field:
```json
{
  "backend": "vllm",
  "state": "switching",
  "switch_progress": {
    "step": "downloading",
    "detail": "Downloading meta-llama/Llama-3.1-8B-Instruct...",
    "started_at": "2026-03-13T10:00:00Z"
  },
  "container_status": { "status": "starting" }
}
```

The `switch_progress` field is only present during an active switch operation. Recovery stores the progress in Redis at `nova:config:inference.switch_progress` (JSON, with TTL of 5 minutes as cleanup).

### Model Catalog Search

New recovery endpoint proxies HuggingFace API / Ollama registry with backend-aware filtering.

```python
# In recovery-service/app/inference/routes.py
@router.get("/api/v1/recovery/inference/models/search")
async def search_models(q: str, backend: str = "vllm", max_vram_gb: float | None = None):
    # For vLLM/SGLang: search HuggingFace API, filter by safetensors format
    # For Ollama: search Ollama library/registry
    # If max_vram_gb provided, estimate and filter by VRAM requirements
    # Returns: [{ id, description, size_gb, vram_estimate_gb, format, downloads }]
```

VRAM estimation: rough heuristic based on parameter count and quantization. For FP16, ~2 bytes per param. For AWQ/GPTQ, ~0.5 bytes per param. Plus ~1GB overhead.

### Model History

Stored in `platform_config` as `inference.recent_models`:
```json
[
  { "model": "meta-llama/Llama-3.2-3B-Instruct", "backend": "vllm", "last_used": "2026-03-13T...", "vram_estimate_gb": 2.5 },
  { "model": "Qwen/Qwen2.5-7B-Instruct-AWQ", "backend": "vllm", "last_used": "2026-03-12T...", "vram_estimate_gb": 4.2 }
]
```
Max 10 entries, ordered by `last_used`. Updated when a model switch completes successfully.

### Recommended Models

A curated JSON file at `data/recommended_models.json`:
```json
[
  {
    "id": "meta-llama/Llama-3.2-3B-Instruct",
    "name": "Llama 3.2 3B",
    "category": "general",
    "min_vram_gb": 2.5,
    "backends": ["vllm", "sglang"],
    "description": "Fast, capable general-purpose model"
  },
  {
    "id": "llama3.2",
    "name": "Llama 3.2 3B",
    "category": "general",
    "min_vram_gb": 2.5,
    "backends": ["ollama"],
    "description": "Fast, capable general-purpose model"
  }
]
```

Categories: `general`, `coding`, `reasoning`, `embedding`. The Models page shows a grid of recommended models filtered by the active backend and detected VRAM.

### Onboarding Wizard

A 6-step wizard shown on first dashboard visit.

**Trigger:** Dashboard checks `platform_config` for `onboarding.completed` after authentication resolves (not during initial mount — must wait for auth to avoid redirect loops when `REQUIRE_AUTH=true`). If not set, redirects to `/onboarding`.

**Steps:**

1. **Welcome** — Brief intro. "Get Started" or "Skip — I'll configure manually". Skip sets `onboarding.completed = true` and navigates to chat.

2. **Hardware Detection** — Reads from `nova:system:hardware` (populated by 12a's `detect_hardware.sh`). Shows GPU model + VRAM, CPU cores, RAM, free disk. Green banner if GPU found ("GPU inference available"), amber if CPU-only ("CPU inference — still fast for smaller models").

3. **Choose Engine** — Radio cards. Recommendation badge based on hardware (uses `get_backend_recommendation()` from `recovery-service/app/inference/hardware.py`, threshold: >=8GB VRAM → vLLM):
   - GPU + >=8GB VRAM: recommend vLLM
   - GPU + <8GB VRAM: recommend Ollama
   - No GPU: recommend Ollama (CPU), hide vLLM/SGLang
   - "Cloud Only" always available
   - Each card: name, 1-line description, why you'd pick it

4. **Pick a Model** — Adapts to engine choice. Shows models from `data/recommended_models.json` filtered by backend and VRAM. Pre-selects the recommended model. HuggingFace search available for power users. Shows model size and VRAM estimate.

5. **Downloading** — Progress tracker using polling of `GET /inference/backend` (same as model switch progress). Steps: Starting container → Downloading model → Loading into GPU → Ready. Shows "one-time download" note.

6. **Ready** — "Start Chatting" button navigates to `/chat`. Notes that everything can be changed in Settings.

**Implementation:**
- Route: `/onboarding`
- Component: `dashboard/src/pages/onboarding/OnboardingWizard.tsx`
- Step components in `dashboard/src/pages/onboarding/steps/`
- Re-runnable: Settings General section gets a "Re-run Setup Wizard" button that clears `onboarding.completed` and navigates to `/onboarding`
- All wizard actions use existing APIs (recovery lifecycle, recovery model search, orchestrator platform_config)

**No CLI changes.** `setup.sh` stays minimal.

### Dashboard File Changes (12b)

| File | Change |
|------|--------|
| `dashboard/src/pages/Models.tsx` | Refactor Local Models section to be backend-aware |
| `dashboard/src/pages/onboarding/OnboardingWizard.tsx` | New — wizard container with step navigation |
| `dashboard/src/pages/onboarding/steps/Welcome.tsx` | New |
| `dashboard/src/pages/onboarding/steps/HardwareDetection.tsx` | New |
| `dashboard/src/pages/onboarding/steps/ChooseEngine.tsx` | New |
| `dashboard/src/pages/onboarding/steps/PickModel.tsx` | New |
| `dashboard/src/pages/onboarding/steps/Downloading.tsx` | New |
| `dashboard/src/pages/onboarding/steps/Ready.tsx` | New |
| `dashboard/src/App.tsx` | Add `/onboarding` route, add redirect logic (after auth) |
| `dashboard/src/pages/settings/GeneralSection.tsx` (or similar) | Add "Re-run Setup Wizard" button |

### Backend File Changes (12b)

| File | Change |
|------|--------|
| `recovery-service/app/inference/controller.py` | Add `switch_model()` method with drain protocol, switch progress tracking |
| `recovery-service/app/inference/routes.py` | Add `POST /inference/backend/{backend}/switch-model`, `GET /inference/models/search` |
| `recovery-service/app/env_manager.py` | Add `VLLM_MODEL`, `SGLANG_MODEL` to `ENV_WHITELIST` |
| `data/recommended_models.json` | New — curated model list |

---

## Phase 12c — SGLang + Custom Endpoints

### SGLang Provider

`SGLangProvider` extends `OpenAICompatibleProvider` — SGLang exposes an OpenAI-compatible API, so the provider is a thin subclass (same pattern as `VLLMProvider`).

**Docker Compose:**
```yaml
nova-sglang:
  <<: *nova-common
  image: lmsysorg/sglang:latest
  container_name: nova-sglang
  profiles: ["local-sglang"]
  volumes:
    - nova-sglang-cache:/root/.cache/huggingface
  environment:
    - SGLANG_MODEL=${SGLANG_MODEL:-meta-llama/Llama-3.2-3B-Instruct}
  entrypoint: ["/bin/sh", "-c"]
  command:
    - >
      python -m sglang.launch_server
      --model-path "$SGLANG_MODEL"
      --host 0.0.0.0
      --port 8000
```

GPU reservations go in `docker-compose.gpu.yml` (same pattern as `nova-vllm`). Volume `nova-sglang-cache` added to the volumes section.

**Recovery registration:** Add to `BACKENDS` dict in `recovery-service/app/inference/controller.py`:
```python
BACKENDS = {
    "ollama": {"profile": "local-ollama", "service": "ollama", "container": "nova-ollama"},
    "vllm": {"profile": "local-vllm", "service": "nova-vllm", "container": "nova-vllm"},
    "sglang": {"profile": "local-sglang", "service": "nova-sglang", "container": "nova-sglang"},
}
```

Model switching works identically to vLLM — `switch_model()` calls `patch_env({"SGLANG_MODEL": new_model})` and restarts.

### Custom Endpoint (RemoteInferenceProvider)

For users running their own inference server that Nova doesn't manage the container for.

**Config in `platform_config`:**
```json
{
  "inference.custom_url": "http://192.168.1.50:8080",
  "inference.custom_auth_header": "Bearer sk-my-key"
}
```

**Provider:**
- `RemoteInferenceProvider` extends `OpenAICompatibleProvider`
- Pointed at user's URL from `inference.custom_url`
- Optional auth header from `inference.custom_auth_header`
- No lifecycle management — no start/stop/drain
- Recovery does periodic health checks (same 30s interval) against the custom URL
- Model discovery via `GET /v1/models` on the custom URL

**Backend selector becomes:** `ollama | vllm | sglang | custom | none`

- `ollama`, `vllm`, `sglang`: managed (start/stop/drain/model switch)
- `custom`: unmanaged (health check + model discovery only)
- `none`: local inference disabled

### LocalInferenceProvider Changes

The `_create_delegate()` method in `llm-gateway/app/providers/local_inference_provider.py` currently handles `ollama` and `vllm`. Two changes needed:

**1. `refresh_config()` (async)** — read custom endpoint config alongside existing backend/state/url reads:
```python
# In refresh_config(), after reading backend, state, url_override:
if backend == "custom":
    custom_url = await self._get_redis_config("inference.custom_url")
    custom_auth = await self._get_redis_config("inference.custom_auth_header")
else:
    custom_url = custom_auth = None
# Pass custom_url, custom_auth to _create_delegate()
```

**2. `_create_delegate()` (sync)** — add sglang and custom branches:
```python
elif backend == "sglang":
    from .sglang_provider import SGLangProvider
    return SGLangProvider(url=url)
elif backend == "custom":
    # custom_url and custom_auth passed in from refresh_config()
    if not custom_url:
        logger.warning("Custom backend selected but no URL configured")
        return None
    from .remote_provider import RemoteInferenceProvider
    return RemoteInferenceProvider(url=custom_url, auth_header=custom_auth)
```

Also update the class docstring to include `"custom"` as a valid `inference.backend` value.

### Settings UI Changes

**Local Inference section updates:**
- Backend dropdown gets `SGLang` and `Custom` options
- When `Custom` selected: URL input, optional auth header field, "Test Connection" button
- Test connection calls `GET /v1/models` on the provided URL and shows result
- When `SGLang` selected: same UX as vLLM (model search, switch, status)

### File Changes (12c)

| File | Change |
|------|--------|
| `llm-gateway/app/providers/sglang_provider.py` | New — thin subclass of `OpenAICompatibleProvider` |
| `llm-gateway/app/providers/remote_provider.py` | New — extends `OpenAICompatibleProvider` with custom URL/auth |
| `llm-gateway/app/providers/__init__.py` | Register new providers |
| `llm-gateway/app/providers/local_inference_provider.py` | Add `sglang` and `custom` branches to `_create_delegate()` |
| `docker-compose.yml` | Add `nova-sglang` service with profile |
| `docker-compose.gpu.yml` | Add GPU reservation for `nova-sglang` |
| `recovery-service/app/inference/controller.py` | Register `sglang` in `BACKENDS` dict, add custom endpoint health check |
| `dashboard/src/pages/settings/LocalInferenceSection.tsx` | Add SGLang/Custom options, custom URL config |
| `dashboard/src/pages/Models.tsx` | Handle SGLang (same as vLLM) and Custom (read-only) |

---

## Phase 12d — Intelligence + Monitoring

### Auto-Recommendations

Extend the existing `get_backend_recommendation()` in `recovery-service/app/inference/hardware.py` to also recommend a specific model:

```python
async def get_recommendation(hardware: dict) -> dict:
    """Returns recommended backend + model based on hardware."""
    # GPU + >=8GB VRAM → vLLM + appropriately sized model from recommended_models.json
    # GPU + <8GB VRAM → Ollama + quantized model
    # No GPU → Ollama CPU + small model (3B or less)
    # Returns: { backend, model, reason }
```

Uses the curated `data/recommended_models.json` (created in 12b) to select the best model for the detected VRAM.

**Used by:**
- Onboarding wizard (Step 3 & 4 pre-selections)
- Settings: suggestion banner if current config differs from recommended ("Based on your hardware, we recommend vLLM with Llama 3.2 3B")

**Endpoint:** `GET /api/v1/recovery/inference/recommendation` — returns `{ backend, model, reason }`

### GPU Monitoring

**Endpoint:** `GET /api/v1/recovery/hardware/gpu-stats`

**Constraint:** `nvidia-smi`/`rocm-smi` are NOT installed in the recovery container (`python:3.12-slim`). GPU detection at runtime only works from the host script (`detect_hardware.sh` → `data/hardware.json`).

**Solution:** Query GPU stats from the running inference container instead:
- **vLLM** exposes metrics at its `/metrics` Prometheus endpoint — includes `vllm:gpu_cache_usage_perc`, memory stats
- **SGLang** similarly exposes metrics
- **Ollama** provides `GET /api/ps` which shows loaded models and memory usage
- For more detailed stats, exec `nvidia-smi` inside the GPU container (which does have the NVIDIA runtime): `docker exec nova-vllm nvidia-smi --query-gpu=... --format=csv`

The recovery service uses `docker exec` against the running inference container to get GPU stats, falling back gracefully if the container isn't running or doesn't have the tools.

Returns:
```json
{
  "gpu_utilization_pct": 45,
  "vram_used_gb": 5.8,
  "vram_total_gb": 8.0,
  "temperature_c": 62
}
```

For no GPU or no running backend: returns `null`.

**Dashboard:** Small GPU stats card shown on Models page (next to active model) and in Local Inference Settings. Polls every 10s when visible (`refetchInterval: 10_000`).

### Inference Performance Metrics

**Gateway changes:**
- Track `tokens_per_second` and `time_to_first_token_ms` per request in the streaming response handler
- Store rolling window (last 5 minutes) of metrics in Redis with TTL

**Endpoint:** `GET /v1/inference/stats`
```json
{
  "requests_5m": 24,
  "avg_tokens_per_sec": 42.5,
  "avg_ttft_ms": 180,
  "error_rate_pct": 0.0,
  "active_model": "meta-llama/Llama-3.2-3B-Instruct",
  "backend": "vllm"
}
```

**Dashboard:** Metric cards alongside active model info — tokens/sec, time to first token, requests served. Only shown when a local backend is active and serving.

### Nginx Configuration Note

The recovery service proxy in nginx (`/recovery-api`) should have `proxy_buffering off` for the polling endpoints to respond promptly. The Vite dev proxy should work without changes.

### File Changes (12d)

| File | Change |
|------|--------|
| `recovery-service/app/inference/hardware.py` | Extend `get_backend_recommendation()` to include model, add `get_gpu_stats()` using docker exec |
| `recovery-service/app/inference/routes.py` | Add `GET /inference/recommendation`, `GET /hardware/gpu-stats` |
| `llm-gateway/app/providers/local_inference_provider.py` | Track tokens/sec, TTFT per request |
| `llm-gateway/app/router.py` | Add `GET /v1/inference/stats` |
| `dashboard/src/pages/Models.tsx` | GPU stats card, performance metrics |
| `dashboard/src/pages/settings/LocalInferenceSection.tsx` | GPU stats card, recommendation banner |

---

## Implementation Order

1. **Phase 12b** (largest): Model library UI + vLLM model switching + onboarding wizard + recommended models
2. **Phase 12c** (medium): SGLang provider + custom endpoints + Settings UI updates
3. **Phase 12d** (smallest): Recommendations + GPU monitoring + performance metrics

Each phase delivers standalone value and can be shipped independently.

## Testing Strategy

All tests follow Nova's integration test convention — hit real running services, `nova-test-` prefix, no mocks.

**Phase 12b tests:**
- Model search endpoint returns filtered results
- vLLM model switch updates `.env` and runs drain protocol (if vLLM available)
- Switch progress appears in backend status response
- Onboarding flow sets `onboarding.completed` in platform_config
- Recommended models filtered by backend and VRAM

**Phase 12c tests:**
- SGLang provider registers and routes correctly
- Custom endpoint health check works with mock server
- Backend selector accepts all 5 options
- `_create_delegate()` returns correct provider for each backend type

**Phase 12d tests:**
- Recommendation function returns correct backend+model for hardware profiles
- GPU stats endpoint returns structured data via docker exec (or null gracefully)
- Inference stats endpoint returns rolling metrics
