---
title: "Inference Backends"
description: "Comparison of local inference backends: Ollama, vLLM, llama.cpp, and SGLang."
---

Nova supports multiple local inference backends. All four expose OpenAI-compatible APIs, and LiteLLM abstracts the provider layer, so switching backends is a configuration change -- not an architecture change.

## Backend comparison

| Capability | Ollama | vLLM | llama.cpp (llama-server) | SGLang |
|-----------|--------|------|--------------------------|--------|
| **Concurrent batching** | Sequential queue (`OLLAMA_NUM_PARALLEL` limited) | Continuous batching -- interleaves tokens across requests | Limited parallel slots via `-np` flag | Continuous batching + RadixAttention |
| **Multi-user serving** | Latency degrades linearly | Near-constant latency up to batch capacity | Better than Ollama, worse than vLLM/SGLang | Best-in-class for shared-prefix workloads |
| **VRAM efficiency** | Loads/unloads full models | PagedAttention -- packs KV caches efficiently | Manual KV cache sizing, efficient for single model | RadixAttention -- caches common prefixes across requests |
| **Model switching** | Hot-swap via `ollama pull`, evicts from VRAM | Single model per instance, restart to switch | Single model per instance | Single model per instance |
| **Quantization** | GGUF (widest variety, community models) | GPTQ, AWQ, FP8, GGUF (recent) | GGUF native (fastest GGUF inference) | GPTQ, AWQ, FP8, GGUF |
| **Structured output** | JSON mode (basic) | Outlines-based JSON schema enforcement | GBNF grammars (powerful, verbose) | Native JSON schema + regex constraints |
| **CPU inference** | Yes (good) | GPU only | Yes (excellent -- original purpose) | GPU only |
| **Setup complexity** | Single binary, trivial | Python env, more config | Single binary, moderate flags | Python env, similar to vLLM |
| **Docker image** | `ollama/ollama` | `vllm/vllm-openai` | `ghcr.io/ggerganov/llama.cpp:server` | `lmsysorg/sglang` |

## Why SGLang is interesting for Nova

SGLang's **RadixAttention** automatically caches shared prefixes across requests. In Nova's architecture, every pipeline agent (Context, Task, Guardrail, Code Review) has a system prompt that is identical across all task executions. With 5 parallel tasks running the same pod, that's 20 agent calls sharing large system prompt prefixes.

SGLang caches these in a radix tree -- subsequent requests skip re-computing attention for the shared prefix. This is a significant speedup for exactly Nova's workload pattern of parallel agent pipelines.

## Recommended backend by workload

| Workload | Recommended backend | Why |
|----------|-------------------|-----|
| **Single user, model experimentation** | Ollama | Hot-swap models, widest GGUF library, zero config |
| **Multi-tenant chat** | vLLM or SGLang | Continuous batching handles concurrent users efficiently |
| **Parallel agent pipelines** | SGLang | RadixAttention prefix caching across agents sharing system prompts |
| **CPU-only / edge deployment** | llama.cpp | Best CPU performance, smallest footprint |
| **Coding sessions (multiple concurrent)** | vLLM or SGLang | Long contexts + concurrent requests need batching |
| **Hybrid (recommended default)** | Ollama + SGLang | Ollama for model variety, SGLang as primary serving engine |

## Docker Compose profiles

Each backend has its own Docker Compose profile. Enable what you need -- run one, two, or all four simultaneously on different ports.

| Profile | Port | Enable with |
|---------|------|-------------|
| `local-ollama` | 11434 | `COMPOSE_PROFILES=local-ollama` |
| `local-vllm` | 8003 | `COMPOSE_PROFILES=local-vllm` |
| `local-sglang` | 8004 | `COMPOSE_PROFILES=local-sglang` |
| `local-llamacpp` | 8005 | `COMPOSE_PROFILES=local-llamacpp` |

Run multiple backends by comma-separating profiles:

```bash
COMPOSE_PROFILES=local-ollama,local-sglang
```

### Example: vLLM service

```yaml
vllm:
  image: vllm/vllm-openai:latest
  profiles: ["local-vllm"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - vllm-models:/root/.cache/huggingface
  environment:
    - MODEL=${VLLM_MODEL:-meta-llama/Llama-3.1-70B-Instruct-AWQ}
    - MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-4096}
    - GPU_MEMORY_UTILIZATION=0.90
  ports: ["8003:8000"]
```

### Example: SGLang service

```yaml
sglang:
  image: lmsysorg/sglang:latest
  profiles: ["local-sglang"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - sglang-models:/root/.cache/huggingface
  environment:
    - MODEL_PATH=${SGLANG_MODEL:-meta-llama/Llama-3.1-70B-Instruct-AWQ}
    - MEM_FRACTION_STATIC=0.88
  ports: ["8004:30000"]
```

### Example: llama.cpp service

```yaml
llama-cpp:
  image: ghcr.io/ggerganov/llama.cpp:server
  profiles: ["local-llamacpp"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - llamacpp-models:/models
  environment:
    - LLAMA_ARG_MODEL=/models/${LLAMACPP_MODEL:-model.gguf}
    - LLAMA_ARG_CTX_SIZE=${LLAMACPP_CTX_SIZE:-4096}
    - LLAMA_ARG_N_GPU_LAYERS=99
    - LLAMA_ARG_PARALLEL=${LLAMACPP_PARALLEL:-4}
  ports: ["8005:8080"]
```

## Configuration variables per backend

| Variable | Backend | Description | Default |
|----------|---------|-------------|---------|
| `VLLM_MODEL` | vLLM | HuggingFace model ID | `meta-llama/Llama-3.1-70B-Instruct-AWQ` |
| `VLLM_MAX_MODEL_LEN` | vLLM | Maximum context length | `4096` |
| `SGLANG_MODEL` | SGLang | HuggingFace model ID | `meta-llama/Llama-3.1-70B-Instruct-AWQ` |
| `LLAMACPP_MODEL` | llama.cpp | GGUF filename in models volume | `model.gguf` |
| `LLAMACPP_CTX_SIZE` | llama.cpp | Context size | `4096` |
| `LLAMACPP_PARALLEL` | llama.cpp | Number of parallel slots | `4` |

## Integration with LLM Gateway

All backends are registered as providers in the LLM Gateway via LiteLLM. The gateway handles:

- Routing requests to the correct backend based on model name
- Translating between OpenAI-compatible format and Nova's internal format
- Health checking and fallback between backends
- The [LLM routing strategy](/nova/docs/configuration#llm-routing-strategies) (`local-first`, `cloud-first`, etc.) applies across all backends
