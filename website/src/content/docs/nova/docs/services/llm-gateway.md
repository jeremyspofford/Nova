---
title: "LLM Gateway"
description: "Multi-provider model routing via LiteLLM with an OpenAI-compatible endpoint. Port 8001."
---

The LLM Gateway is Nova's model routing layer. It exposes a unified API that translates requests to any configured provider -- Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, GitHub Models, and subscription-based providers (Claude Max, ChatGPT Plus).

## At a glance

| Property | Value |
|----------|-------|
| **Port** | 8001 |
| **Framework** | FastAPI + LiteLLM |
| **State store** | Redis (db 1) |
| **Source** | `llm-gateway/` |

## Key responsibilities

- **Model routing** -- resolve model IDs to provider instances and forward requests
- **OpenAI compatibility** -- expose `/v1/chat/completions` and `/v1/models` so any OpenAI-compatible tool works out of the box
- **Subscription auth** -- use Claude Max/Pro and ChatGPT Plus/Pro subscriptions as zero-cost providers
- **Rate limiting** -- per-provider daily quotas enforced via Redis sliding window
- **Response caching** -- cache deterministic (temperature=0) completions to avoid duplicate API calls
- **Ollama sync** -- auto-discover locally pulled Ollama models and register them at startup

## Routing strategies

The routing strategy is configurable at runtime via the platform config:

| Strategy | Behavior |
|----------|----------|
| `local-only` | Only use Ollama. Fail if offline. |
| `local-first` | Try Ollama first, fall back to cloud. **(default)** |
| `cloud-only` | Skip Ollama entirely, use cloud providers. |
| `cloud-first` | Try cloud first, use Ollama as backup. |

## Provider types

### Subscription providers (zero API cost)

| Provider | Setup | Model prefix |
|----------|-------|-------------|
| **Claude Max/Pro** | Run `claude setup-token` or auto-read from `~/.claude/.credentials.json` | `claude-max/` |
| **ChatGPT Plus/Pro** | Run `codex login` or auto-read from `~/.codex/auth.json` | `chatgpt/` |

### Free-tier API keys

| Provider | Daily limit | Env var |
|----------|------------|---------|
| Ollama | Unlimited (local) | -- |
| Groq | 14,400 req/day | `GROQ_API_KEY` |
| Gemini | 250 req/day | `GEMINI_API_KEY` |
| Cerebras | 1M tokens/day | `CEREBRAS_API_KEY` |
| OpenRouter | 50+ req/day | `OPENROUTER_API_KEY` |
| GitHub Models | 50-150 req/day | `GITHUB_TOKEN` |

### Paid API keys

| Provider | Env var |
|----------|---------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |

## Key endpoints

### Nova internal API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/complete` | Non-streaming LLM completion |
| POST | `/stream` | SSE streaming completion |
| POST | `/embed` | Generate text embeddings |

### OpenAI-compatible API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Chat completions (streaming and non-streaming) |
| GET | `/v1/models` | List all registered model IDs |

### Discovery

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/models/discover` | Discover available models from all providers |
| GET | `/v1/models/ollama/*` | Ollama model management |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | -- |
| `OPENAI_API_KEY` | OpenAI API key | -- |
| `OLLAMA_BASE_URL` | Ollama API URL | `http://ollama:11434` |
| `GROQ_API_KEY` | Groq API key | -- |
| `GEMINI_API_KEY` | Gemini API key | -- |
| `CEREBRAS_API_KEY` | Cerebras API key | -- |
| `OPENROUTER_API_KEY` | OpenRouter API key | -- |
| `GITHUB_TOKEN` | GitHub PAT for GitHub Models | -- |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/1` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins | `*` |

## Usage example

```bash
# List available models
curl http://localhost:8001/v1/models | jq '.data[].id'

# OpenAI-compatible completion
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-max/claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello from Nova"}]
  }'

# Nova internal completion
curl http://localhost:8001/complete \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-max/claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Implementation notes

- **LiteLLM abstraction** -- all provider calls go through LiteLLM for unified request/response translation
- **Provider auto-detection** -- providers are registered at startup based on available credentials (env vars, credential files, keychain)
- **Rate limiting** -- per-provider daily quotas tracked in Redis; returns HTTP 429 when exhausted
- **Response cache** -- temperature=0 requests are cached to avoid redundant API calls; cache is keyed on the full request body (excluding metadata)
- **Translation layer** -- `openai_compat.py` converts between OpenAI wire format and Nova's internal `CompleteRequest`/`CompleteResponse` types
