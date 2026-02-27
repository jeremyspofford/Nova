# IDE Integration

Nova exposes an OpenAI-compatible API on the LLM gateway (`http://localhost:8001/v1`).
Any tool that speaks the OpenAI chat completions protocol works out of the box.

---

## Continue.dev (VS Code / JetBrains)

### Quick start

1. Install the [Continue extension](https://marketplace.visualstudio.com/items?itemName=Continue.continue)
2. Open the config: **Cmd+Shift+P** → `Continue: Open config.json`
3. Add an entry to the `models` array:

```json
{
  "models": [
    {
      "title": "Nova (Claude Sonnet)",
      "provider": "openai",
      "model": "claude-max/claude-sonnet-4-6",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    }
  ]
}
```

`apiKey` is required by Continue's JSON schema but Nova ignores its value.
`apiBase` is the only thing that matters — it redirects traffic from `api.openai.com` to Nova.

### Recommended model set

Add multiple entries to switch models from the Continue sidebar:

```json
{
  "models": [
    {
      "title": "Nova · Sonnet (fast)",
      "provider": "openai",
      "model": "claude-max/claude-sonnet-4-5",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    },
    {
      "title": "Nova · Sonnet (latest)",
      "provider": "openai",
      "model": "claude-max/claude-sonnet-4-6",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    },
    {
      "title": "Nova · Opus (most capable)",
      "provider": "openai",
      "model": "claude-max/claude-opus-4",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    },
    {
      "title": "Nova · GPT-4o",
      "provider": "openai",
      "model": "openai/gpt-4o",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    }
  ]
}
```

### Verify available models

```bash
curl http://localhost:8001/v1/models | jq '.data[].id'
```

Returns all 39 registered model IDs.

### With API key auth enabled

If `REQUIRE_AUTH=true`, create a key first:

```bash
curl -X POST http://localhost:8000/api/v1/keys \
  -H "X-Admin-Secret: your-admin-secret" \
  -H "Content-Type: application/json" \
  -d '{"name": "continue-dev", "rate_limit_rpm": 120}'
```

Use the returned `key` value (shown once) as the `apiKey` field in the config above.

---

## Cursor

Same approach — Cursor supports custom OpenAI-compatible endpoints:

1. **Settings** → **Models** → **Add model**
2. Set **Base URL** to `http://localhost:8001/v1`
3. Set **API Key** to any placeholder
4. Use any Nova model ID as the model name

---

## Aider (terminal)

```bash
aider \
  --openai-api-base http://localhost:8001/v1 \
  --openai-api-key unused \
  --model claude-max/claude-sonnet-4-6
```

---

## Raw API (curl / scripts)

```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-max/claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello from Nova"}]
  }'
```

---

## How it works

```
IDE / tool
    │  POST /v1/chat/completions  (OpenAI format)
    ▼
LLM Gateway  :8001
    │  translates OpenAI → Nova internal format
    │  forwards to registered provider (Anthropic, OpenAI, Ollama, …)
    ▼
Provider API
    │  response
    ▼
LLM Gateway
    │  translates provider response → OpenAI format
    ▼
IDE / tool  ← looks identical to talking directly to OpenAI
```

The translation lives in `llm-gateway/app/openai_compat.py`.
