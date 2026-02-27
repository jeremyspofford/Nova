# Nova

Nova is a self-directed autonomous AI platform. Define a goal and Nova breaks it into subtasks, executes them through a coordinated pipeline of specialized agents, evaluates progress, re-plans, and completes — with minimal human intervention.

Built by [Aria Labs](https://arialabs.ai).

---

## Architecture

| Service | Port | Role |
|---|---|---|
| orchestrator | 8000 | Agent lifecycle, tool dispatch, session state, pipeline queue, MCP |
| llm-gateway | 8001 | Model routing — Anthropic, OpenAI, Ollama, Groq, Gemini, and more |
| memory-service | 8002 | Embedding + semantic retrieval via pgvector |
| chat-api | 8080 | WebSocket streaming for external clients |
| dashboard | 3000 | React admin UI |
| postgres | 5432 | pgvector/pg16 — agents, tasks, pods, platform config |
| redis | 6379 | Agent state, task queue, rate limiting, session memory |
| ollama | 11434 | Local model serving (dev) |

---

## Quick Start

**1. Copy and configure environment:**

```bash
cp .env.example .env
# Edit .env with your API keys and secrets
```

**2. Start all services:**

```bash
make dev
# or: docker compose up --build --watch
```

**3. Open the dashboard:** http://localhost:3000

---

## Environment

See [.env.example](.env.example) for all configurable values. Required fields:

- `POSTGRES_PASSWORD` — database password
- `NOVA_ADMIN_SECRET` — dashboard admin password (default insecure, change before deployment)
- At least one model provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)

---

## Tech Stack

- **Backend:** Python + FastAPI + asyncpg + asyncio
- **Frontend:** Vite + React + TypeScript + Tailwind + TanStack Query
- **Database:** PostgreSQL 16 + pgvector
- **Queue:** Redis (BRPOP task dispatch)
- **Containers:** Docker Compose with hot reload

---

## IDE Integration

Nova exposes an OpenAI-compatible endpoint at `http://localhost:8000/v1`. Compatible with Cursor, Continue.dev, Aider, and any OpenAI-API client.

See [docs/ide-integration.md](docs/ide-integration.md) for setup instructions.
