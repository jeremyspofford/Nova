---
title: "Inference Backends"
description: "How Nova manages local inference backends -- Ollama, vLLM, and SGLang -- with automatic lifecycle management, hardware detection, and one-click switching."
---

Nova manages local inference backend lifecycle for you. Select a backend from the dashboard, and Nova handles pulling the container image, starting it with the right GPU flags, health monitoring, and graceful switching -- no manual Docker Compose profile editing required.

All supported backends expose OpenAI-compatible APIs, and the LLM Gateway's `LocalInferenceProvider` abstracts the active backend so the rest of Nova doesn't need to know which one is running.

## Backend comparison

| Capability | Ollama | vLLM | SGLang |
|-----------|--------|------|--------|
| **Concurrent batching** | Sequential queue (`OLLAMA_NUM_PARALLEL` limited) | Continuous batching -- interleaves tokens across requests | Continuous batching + RadixAttention |
| **Multi-user serving** | Latency degrades linearly | Near-constant latency up to batch capacity | Best-in-class for shared-prefix workloads |
| **VRAM efficiency** | Loads/unloads full models | PagedAttention -- packs KV caches efficiently | RadixAttention -- caches common prefixes across requests |
| **Model switching** | Hot-swap via `ollama pull`, evicts from VRAM | Single model per instance, restart to switch | Single model per instance |
| **Quantization** | GGUF (widest variety, community models) | GPTQ, AWQ, FP8, GGUF (recent) | GPTQ, AWQ, FP8, GGUF |
| **Structured output** | JSON mode (basic) | Outlines-based JSON schema enforcement | Native JSON schema + regex constraints |
| **CPU inference** | Yes (good) | GPU only | GPU only |
| **Setup complexity** | Single binary, trivial | Python env, more config | Python env, similar to vLLM |
| **Docker image** | `ollama/ollama` | `vllm/vllm-openai` | `lmsysorg/sglang` |

## Why SGLang is interesting for Nova

SGLang's **RadixAttention** automatically caches shared prefixes across requests. In Nova's architecture, every pipeline agent (Context, Task, Guardrail, Code Review) has a system prompt that is identical across all task executions. With 5 parallel tasks running the same pod, that's 20 agent calls sharing large system prompt prefixes.

SGLang caches these in a radix tree -- subsequent requests skip re-computing attention for the shared prefix. This is a significant speedup for exactly Nova's workload pattern of parallel agent pipelines.

## Recommended backend by workload

| Workload | Recommended backend | Why |
|----------|-------------------|-----|
| **Single user, model experimentation** | Ollama | Hot-swap models, widest GGUF library, zero config |
| **Multi-tenant chat** | vLLM or SGLang | Continuous batching handles concurrent users efficiently |
| **Parallel agent pipelines** | SGLang | RadixAttention prefix caching across agents sharing system prompts |
| **CPU-only / edge deployment** | Ollama | Best CPU performance among managed backends |
| **Coding sessions (multiple concurrent)** | vLLM or SGLang | Long contexts + concurrent requests need batching |

:::note
llama.cpp is not a managed backend but can still be used as a custom OpenAI-compatible endpoint. For CPU-only deployments, Ollama is the recommended managed option.
:::

## Managed backends

Nova currently manages two backends -- **Ollama** and **vLLM** -- with SGLang planned. Only one local backend runs at a time. Each backend is defined as a Docker Compose service with a profile, and the recovery service manages its lifecycle.

| Backend | Profile | Container | Port | Status |
|---------|---------|-----------|------|--------|
| Ollama | `local-ollama` | `nova-ollama` | 11434 | Managed |
| vLLM | `local-vllm` | `nova-vllm` | 8000 | Managed |
| SGLang | `local-sglang` | `nova-sglang` | 8000 | Planned |

Users do not set `COMPOSE_PROFILES` manually for inference backends. The recovery service starts and stops profiled services via its Docker Compose integration.

## Hardware detection

Nova detects your hardware at two points:

1. **Setup time** -- `setup.sh` runs GPU detection on the host and writes results to `data/hardware.json`
2. **Runtime** -- the recovery service reads `data/hardware.json` on startup and syncs it to Redis (`nova:system:hardware` on db7)

Detection covers:

- GPU vendor (NVIDIA via `nvidia-smi`, AMD via `rocm-smi`)
- GPU model and VRAM per device
- Available Docker GPU runtime (`nvidia-container-toolkit`, ROCm)
- CPU cores, total RAM, free disk space

The dashboard uses these results to recommend a backend:

| Hardware | Recommendation |
|----------|---------------|
| NVIDIA GPU with 8+ GB VRAM | vLLM |
| AMD GPU (ROCm) | vLLM (ROCm build) |
| CPU only | Ollama |
| No local hardware | Cloud providers |

## Backend lifecycle

The recovery service manages the full lifecycle of inference containers using Docker Compose profiles.

### Starting a backend

When you select a backend in the dashboard:

1. If a different backend is already running, Nova drains and stops it first (see [backend switching](#backend-switching-protocol))
2. Recovery sets `nova:config:inference.state` to `starting` and `nova:config:inference.backend` to the selected backend
3. Recovery starts the profiled Compose service with the correct GPU flags
4. Recovery polls the container's health endpoint until it responds (up to 120s timeout)
5. State is set to `ready` -- the LLM Gateway begins routing to the new backend
6. A background health monitor starts checking the container every 30 seconds

Container images are pulled lazily on first backend selection, not at install time. This requires internet access for the initial pull.

### Health monitoring

The recovery service runs a background health check every 30 seconds against the active inference container. After 3 consecutive failures:

1. Recovery attempts to restart the container
2. On success, health counter resets and state returns to `ready`
3. On failure, backoff increases exponentially (30s, 60s, 120s) and state is set to `error`

The dashboard shows the current backend state -- users can see if their backend is running, starting, or in an error state.

### Stopping a backend

Stopping follows the drain protocol described below, then stops the Compose service and sets the backend to `none`.

## Backend switching protocol

When switching from one backend to another (e.g., Ollama to vLLM):

1. Recovery sets `nova:config:inference.state` to `draining`
2. The LLM Gateway reads this state on its next config refresh (5s cache TTL) and stops routing new requests to the local backend -- new requests fall back to cloud providers (if configured) or return 503
3. Recovery polls the gateway's `GET /health/inflight` endpoint, waiting up to **15 seconds** for in-flight local requests to complete
4. After drain completes (or timeout expires), recovery stops the old container
5. Recovery starts the new container and waits for its health endpoint to respond
6. State transitions: `starting` then `ready`
7. The gateway detects the new backend and begins routing to it

If the new backend fails to start within 120 seconds, state is set to `error`. Cloud fallback continues to serve requests, and the dashboard shows the failure.

## Configuration

All inference backend settings are configured through the dashboard UI and stored in Redis -- not in `.env` files.

### Redis keys

| Key | Purpose | Values |
|-----|---------|--------|
| `nova:config:inference.backend` | Active backend | `ollama`, `vllm`, `none` |
| `nova:config:inference.state` | Lifecycle state | `ready`, `starting`, `draining`, `error`, `stopped` |
| `nova:config:inference.url` | Backend URL override | Empty = use default for backend |
| `nova:system:hardware` | Detected hardware info | JSON (GPU, CPU, RAM, disk) |

### What stays in .env

Only bootstrap and security settings:

- `POSTGRES_PASSWORD`, `ADMIN_SECRET`, `NOVA_WORKSPACE`
- `DEFAULT_CHAT_MODEL` -- initial default, overridden by UI after first use
- API keys -- also settable via the dashboard, `.env` is a fallback for headless deploys

## Integration with LLM Gateway

The LLM Gateway uses a `LocalInferenceProvider` that wraps whichever backend is currently active.

### How it works

1. `LocalInferenceProvider` reads `nova:config:inference.backend` and `nova:config:inference.state` from Redis (cached for 5 seconds)
2. Based on the backend value, it creates and delegates to the appropriate provider class:
   - `OllamaProvider` for Ollama
   - `VLLMProvider` (extends `OpenAICompatibleProvider`) for vLLM
3. If the backend changes, the delegate is recreated on the next config refresh -- requests already in-flight on the old delegate complete normally
4. If state is `draining`, `starting`, `error`, or the backend is `none`, `is_available` returns `False` and routing skips local, falling through to cloud

### Provider classes

| Class | Protocol | Notes |
|-------|----------|-------|
| `OpenAICompatibleProvider` | OpenAI `/v1/chat/completions`, `/v1/embeddings` | Base class for vLLM and SGLang |
| `VLLMProvider` | Extends above | Thin wrapper -- vLLM speaks native OpenAI format |
| `OllamaProvider` | Ollama API | Existing provider, unchanged |

### Local model detection

The `LocalInferenceProvider` maintains a set of models discovered from the active backend's `/v1/models` endpoint. Any model in that set is treated as "local" for routing strategy purposes. This replaces the old hardcoded model list. The set refreshes on backend changes and periodically during discovery runs.

### Routing strategies

The existing routing strategies -- `local-first`, `cloud-first`, `local-only`, `cloud-only` -- work unchanged. The difference is that "local" now means whichever managed backend is active, rather than a hardcoded Ollama instance.

Fallback chain: `LocalInferenceProvider` (active backend) then cloud providers.

## Custom endpoints

For backends Nova doesn't manage (llama.cpp, LMStudio, a remote vLLM instance, etc.), configure them as custom OpenAI-compatible endpoints. These coexist alongside the managed backend and are not affected by backend switching.
