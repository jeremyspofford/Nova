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

### Prerequisites
- [Docker Desktop](https://docker.com/products/docker-desktop) (includes Docker Compose)

### Install
```bash
git clone https://github.com/arialabs/nova.git
cd nova
./setup
```

The setup wizard asks a few questions and starts everything.
Open **http://localhost:3001** when it's done.

### Remote GPU (optional)
If you have a separate machine with a GPU for AI inference:
```bash
# Run this ON the GPU machine:
bash <(curl -s https://raw.githubusercontent.com/arialabs/nova/main/scripts/setup-remote-ollama.sh)
```
Then re-run `./setup` on the Nova machine and choose "Remote GPU".

### Manual configuration
If you prefer to skip the wizard, copy `.env.example` to `.env`, edit it, and run `make dev`.
See [.env.example](.env.example) for all configurable values.

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
